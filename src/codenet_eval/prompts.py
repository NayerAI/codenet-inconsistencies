"""Prompt construction for the inconsistency-detection query.

Two flavours, selected by the source ``kind``:

* ``program``  -- full stdin/stdout programs (CodeNet). The diverging input is
  stdin content.
* ``function`` -- standalone functions solving the same task (TransCoder,
  HumanEval-X). The diverging input is a concrete set of arguments / a call.

Both ask for the same strict JSON schema so downstream parsing is uniform.
"""

from __future__ import annotations

import re
from typing import Optional

_SCHEMA = """\
Respond with a SINGLE JSON object and NOTHING else, using exactly this schema:
{
  "inconsistent": boolean,          // true if a diverging input exists
  "confidence": number,             // 0.0 - 1.0
  "category": string,               // short label, e.g. "integer_overflow",
                                    // "float_precision", "none"
  "reasoning": string,              // brief justification
  "divergence_input": string|null,  // the diverging input (see below), or null
  "expected_output_a": string|null, // expected result of A on that input
  "expected_output_b": string|null  // expected result of B on that input
}
Do not wrap the JSON in markdown fences."""

SYSTEM_PROMPT_PROGRAM = f"""\
You are a meticulous program-analysis engine. You are given two programs that \
were both submitted as accepted solutions to the SAME competitive-programming \
problem, but written in DIFFERENT programming languages. Their intended \
behaviour is identical, yet subtle differences (integer width and overflow, \
integer vs. floating-point division, rounding, default output precision, input \
parsing, locale, edge cases, etc.) can make them disagree on some inputs.

Both programs read from standard input and write to standard output. Decide \
whether there exists a VALID input on which the two programs produce DIFFERENT \
output. If so, provide one concrete, minimal example. "divergence_input" must be \
the exact stdin content; "expected_output_a"/"expected_output_b" the exact stdout \
of each program.

Reason carefully about edge cases. Only claim an inconsistency you are \
reasonably confident about. If the programs are equivalent for all valid \
inputs, set inconsistent to false.

{_SCHEMA}
"""

_DRIVER_SCHEMA = """\
Respond with a SINGLE JSON object and NOTHING else, using exactly this schema:
{
  "inconsistent": boolean,          // true if diverging arguments exist
  "confidence": number,             // 0.0 - 1.0
  "category": string,               // short label, e.g. "integer_overflow", "none"
  "reasoning": string,              // brief justification
  "divergence_input": string|null,  // the arguments, stated unambiguously, or null
  "expected_output_a": string|null, // value function A yields for those arguments
  "expected_output_b": string|null, // value function B yields for those arguments
  "program_a": string|null,         // see below
  "program_b": string|null          // see below
}
program_a / program_b: when inconsistent is true, each must be a COMPLETE, \
self-contained, runnable program in language A / language B that includes the \
given function code VERBATIM, calls it on divergence_input, and prints ONLY the \
returned value to standard output (one line, no extra text). The program must \
compile and run as-is with no arguments and no stdin. Use null when inconsistent \
is false.
Do not wrap the JSON in markdown fences."""

_FUNCTION_INTRO = """\
You are a meticulous program-analysis engine. You are given two FUNCTIONS that \
implement the SAME task (same intended behaviour and, up to language idioms, the \
same signature) in DIFFERENT programming languages. Their intended behaviour is \
identical, yet subtle differences (integer width and overflow, integer vs. \
floating-point division, rounding, truncation, off-by-one edge cases, handling \
of empty/negative/boundary arguments, etc.) can make them disagree on some \
arguments.

Decide whether there exist VALID arguments on which the two functions return \
(or print) DIFFERENT results. If so, provide one concrete, minimal example. \
"divergence_input" must state the exact arguments unambiguously (e.g. a call \
like f([1,2], 3) or a JSON object of argument values).

Reason carefully about edge cases. Only claim an inconsistency you are \
reasonably confident about. If the functions are equivalent for all valid \
arguments, set inconsistent to false."""

SYSTEM_PROMPT_FUNCTION = f"{_FUNCTION_INTRO}\n\n{_SCHEMA}\n"
SYSTEM_PROMPT_FUNCTION_DRIVERS = f"{_FUNCTION_INTRO}\n\n{_DRIVER_SCHEMA}\n"


def _code_block(language: str, code: str) -> str:
    fence = language.lower().replace("++", "pp").replace("#", "sharp")
    return f"```{fence}\n{code}\n```"


# --- transpilation experiment ----------------------------------------------
SYSTEM_PROMPT_TRANSPILE = """\
You are an expert programmer performing code translation. Translate the given \
function from the source language to the target language while EXACTLY \
preserving its semantics: for every input, the translated function must return \
the SAME value the source function returns. Do not "fix", improve, or idiomise \
behaviour -- reproduce it faithfully, including any edge-case, overflow, \
rounding or truncation behaviour.

Keep the target function's name and signature exactly as given in the target \
declaration. Output ONLY the target-language code for the function (with any \
imports it needs). No explanation, no markdown fences.
"""


def build_transpile_messages(
    source_language: str,
    source_code: str,
    target_language: str,
    target_declaration: str,
) -> list[dict[str, str]]:
    user = (
        f"Source language: {source_language}\n"
        f"Target language: {target_language}\n\n"
        f"Target declaration (keep this exact signature):\n{target_declaration}\n\n"
        f"Source function to translate:\n{_code_block(source_language, source_code)}\n\n"
        f"Return only the {target_language} code."
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT_TRANSPILE},
        {"role": "user", "content": user},
    ]


_FENCE = re.compile(r"```[a-zA-Z0-9_+#]*\n(.*?)```", re.DOTALL)


def extract_code(text: str) -> str:
    """Pull code out of an LLM reply: the first fenced block if present, else
    the whole text (stripped)."""
    if not text:
        return ""
    m = _FENCE.search(text)
    return (m.group(1) if m else text).strip()


def build_messages(
    problem_id: str,
    language_a: str,
    code_a: str,
    language_b: str,
    code_b: str,
    description: Optional[str] = None,
    sample_input: Optional[str] = None,
    sample_output: Optional[str] = None,
    unit_kind: str = "program",
    request_drivers: bool = False,
) -> list[dict[str, str]]:
    is_function = unit_kind == "function"
    if is_function:
        system = SYSTEM_PROMPT_FUNCTION_DRIVERS if request_drivers else SYSTEM_PROMPT_FUNCTION
    else:
        system = SYSTEM_PROMPT_PROGRAM
    noun = "functions" if is_function else "programs"

    parts: list[str] = [f"Problem id: {problem_id}"]
    if not is_function:
        parts.append("Both programs read from standard input and write to standard output.")
    if description:
        parts.append("\nProblem statement (may be truncated):\n" + description)
    if sample_input is not None and sample_output is not None:
        parts.append(
            "\nA sample input/output pair for reference:\n"
            f"INPUT:\n{sample_input}\nEXPECTED OUTPUT:\n{sample_output}"
        )
    parts.append(f"\n=== PROGRAM A ({language_a}) ===\n" + _code_block(language_a, code_a))
    parts.append(f"\n=== PROGRAM B ({language_b}) ===\n" + _code_block(language_b, code_b))
    parts.append(
        f"\nNow analyse whether an input exists on which the two {noun} produce "
        "different results, and answer with the JSON object described in the "
        "system message."
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(parts)},
    ]

"""Prompt construction for the inconsistency-detection query.

Two flavours, selected by the source ``kind``:

* ``program``  -- full stdin/stdout programs (CodeNet). The diverging input is
  stdin content.
* ``function`` -- standalone functions solving the same task (TransCoder,
  HumanEval-X). The diverging input is a concrete set of arguments / a call.

Both ask for the same strict JSON schema so downstream parsing is uniform.
"""

from __future__ import annotations

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

SYSTEM_PROMPT_FUNCTION = f"""\
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
like f([1,2], 3) or a JSON object of argument values); "expected_output_a"/\
"expected_output_b" the value each function yields for those arguments.

Reason carefully about edge cases. Only claim an inconsistency you are \
reasonably confident about. If the functions are equivalent for all valid \
arguments, set inconsistent to false.

{_SCHEMA}
"""


def _code_block(language: str, code: str) -> str:
    fence = language.lower().replace("++", "pp").replace("#", "sharp")
    return f"```{fence}\n{code}\n```"


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
) -> list[dict[str, str]]:
    is_function = unit_kind == "function"
    system = SYSTEM_PROMPT_FUNCTION if is_function else SYSTEM_PROMPT_PROGRAM
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

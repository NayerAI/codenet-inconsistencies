"""Prompt construction for the inconsistency-detection query.

The model is asked to compare two programs that are meant to solve the same
problem and to return a strict JSON object.  Keeping the schema small and
explicit makes the response easy to parse and to verify downstream.
"""

from __future__ import annotations

from typing import Optional

SYSTEM_PROMPT = """\
You are a meticulous program-analysis engine. You are given two programs that \
were both submitted as accepted solutions to the SAME competitive-programming \
problem, but written in DIFFERENT programming languages. Because they solved \
the same problem their intended behaviour is identical, yet subtle differences \
(integer width and overflow, integer vs. floating-point division, rounding, \
default output precision, off-by-one edge cases, input parsing, locale, etc.) \
can make them disagree on some inputs.

Your job: decide whether there exists a VALID input on which the two programs \
produce DIFFERENT outputs. If such an input exists, provide one concrete, \
minimal example together with the output you expect from each program.

Reason carefully about edge cases. Only claim an inconsistency you are \
reasonably confident about. If the programs are equivalent for all valid \
inputs, say so.

Respond with a SINGLE JSON object and NOTHING else, using exactly this schema:
{
  "inconsistent": boolean,          // true if a diverging input exists
  "confidence": number,             // 0.0 - 1.0
  "category": string,               // short label, e.g. "integer_overflow",
                                    // "float_precision", "none"
  "reasoning": string,              // brief justification
  "divergence_input": string|null,  // exact stdin content for both programs,
                                    // or null if inconsistent is false
  "expected_output_a": string|null, // expected stdout of PROGRAM A on that input
  "expected_output_b": string|null  // expected stdout of PROGRAM B on that input
}
Do not wrap the JSON in markdown fences.
"""


def _code_block(language: str, code: str) -> str:
    return f"```{language.lower()}\n{code}\n```"


def build_messages(
    problem_id: str,
    language_a: str,
    code_a: str,
    language_b: str,
    code_b: str,
    description: Optional[str] = None,
    sample_input: Optional[str] = None,
    sample_output: Optional[str] = None,
) -> list[dict[str, str]]:
    parts: list[str] = [
        f"Problem id: {problem_id}",
        "Both programs read from standard input and write to standard output.",
    ]
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
        "\nNow analyse whether an input exists on which PROGRAM A and PROGRAM B "
        "produce different outputs, and answer with the JSON object described "
        "in the system message."
    )

    user = "\n".join(parts)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]

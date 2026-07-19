"""Extract concrete test inputs from a HumanEval-X ``test`` field.

The Python ``test`` is a ``check(candidate)`` function full of asserts that call
``candidate(<args>)``.  We parse it with ``ast`` and collect the literal
argument tuples of every call to the candidate -- the test *inputs*.  Expected
outputs are derived later by running the reference implementations, so we only
need the inputs here.

Asserts whose arguments are not literals (built in loops, from variables, etc.)
are skipped; a problem with no literal-argument asserts yields no inputs.
"""

from __future__ import annotations

import ast
from typing import Any


def parse_test_inputs(test_src: str, max_inputs: int = 40) -> list[list[Any]]:
    """Return a list of argument lists, one per usable assert in ``test_src``."""
    try:
        tree = ast.parse(test_src)
    except SyntaxError:
        return []

    candidate = _candidate_name(tree)
    if candidate is None:
        return []

    inputs: list[list[Any]] = []
    seen: set = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == candidate
            and not node.keywords
        ):
            try:
                args = [ast.literal_eval(a) for a in node.args]
            except (ValueError, SyntaxError, TypeError):
                continue
            key = repr(args)
            if key in seen:
                continue
            seen.add(key)
            inputs.append(args)
            if len(inputs) >= max_inputs:
                break
    return inputs


def _candidate_name(tree: ast.Module) -> str | None:
    """The parameter name of ``check`` (or the first function's first arg)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "check" and node.args.args:
            return node.args.args[0].arg
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.args.args:
            return node.args.args[0].arg
    return None

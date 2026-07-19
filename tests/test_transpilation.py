"""Tests for the transpilation false-negative experiment."""

import shutil

import pytest

from codenet_eval.config import Config
from codenet_eval.hxtest import parse_test_inputs
from codenet_eval.transpilation import TranspilationRunner

TOOLCHAINS = all(shutil.which(b) for b in ("gcc", "python3"))

# A problem "divide(a, b)" where the SOURCE (Python) uses integer semantics and
# the TARGET reference (C++) uses float semantics -> they diverge on (7, 2).
UNIT = {
    "problem_id": "d",
    "source_language": "Python",
    "target_language": "C++",
    "source_declaration": "def divide(a: int, b: int) -> float:",
    "source_code": "def divide(a: int, b: int) -> float:\n    return a // b\n",   # 7//2 = 3
    "target_declaration": "double divide(int a, int b)",
    "target_ref_code": "double divide(int a, int b){ return (double)a / b; }",    # 3.5
    "test_inputs": [[7, 2], [6, 3], [8, 2]],   # only (7,2) is distinguishing
}

GEN_STRICT_SOURCE = "double divide(int a, int b){ return a / b; }"        # 3  -> source
GEN_RELAXED_TARGET = "double divide(int a, int b){ return (double)a / b; }"  # 3.5 -> target
GEN_WRONG = "double divide(int a, int b){ return 0; }"                    # neither


def _runner():
    cfg = Config.from_dict({
        "data_dir": "/tmp/none",
        "dataset": {"type": "humaneval_x"},
        "experiment": {"type": "transpilation"},
        "languages": ["Python", "C++"],
    })
    return TranspilationRunner(cfg)


def test_parse_test_inputs():
    test = (
        "def check(candidate):\n"
        "    assert candidate([1, 2], 3) == 6\n"
        "    assert candidate([], 0) == 0\n"
        "    x = candidate([9], 1)\n"          # non-literal target var -> the call args ARE literal
    )
    inputs = parse_test_inputs(test)
    assert [ [1, 2], 3 ] in inputs
    assert [[], 0] in inputs
    assert [[9], 1] in inputs


@pytest.mark.skipif(not TOOLCHAINS, reason="gcc + python3 required")
def test_classify_false_negative():
    r = _runner()._classify(UNIT, GEN_STRICT_SOURCE)
    assert r["n_distinguishing"] == 1          # (7,2): 3 vs 3.5
    assert r["passes_source"] is True and r["passes_target"] is False
    assert r["category"] == "false_negative"


@pytest.mark.skipif(not TOOLCHAINS, reason="gcc + python3 required")
def test_classify_relaxed():
    r = _runner()._classify(UNIT, GEN_RELAXED_TARGET)
    assert r["passes_target"] is True and r["passes_source"] is False
    assert r["category"] == "relaxed"


@pytest.mark.skipif(not TOOLCHAINS, reason="gcc + python3 required")
def test_classify_incorrect():
    r = _runner()._classify(UNIT, GEN_WRONG)
    assert r["passes_target"] is False and r["passes_source"] is False
    assert r["category"] == "incorrect"


@pytest.mark.skipif(not TOOLCHAINS, reason="gcc + python3 required")
def test_classify_consistent_when_no_distinguishing_input():
    unit = dict(UNIT, test_inputs=[[6, 3], [8, 2]])  # both agree (2, 4)
    r = _runner()._classify(unit, GEN_RELAXED_TARGET)
    assert r["n_distinguishing"] == 0
    assert r["category"] == "consistent"


@pytest.mark.skipif(not TOOLCHAINS, reason="gcc + python3 required")
def test_classify_uncompilable_generated_is_incorrect():
    r = _runner()._classify(UNIT, "double divide(int a,int b){ this is not code }")
    assert r["passes_target"] is False and r["passes_source"] is False
    assert r["category"] == "incorrect"

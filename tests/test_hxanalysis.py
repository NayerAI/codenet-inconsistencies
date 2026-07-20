"""Tests for the HumanEval-X dataset-level test-case analysis."""

import json
import shutil

import pytest

from codenet_eval.config import Config
from codenet_eval.hxanalysis import HumanEvalXAnalysis, format_analysis

TOOLCHAINS = all(shutil.which(b) for b in ("gcc", "python3"))


def _rec(decl, sol, test):
    return {"declaration": decl, "prompt": "", "canonical_solution": sol, "test": test}


# problem 0: divide(a,b) -- Python true division vs C++ integer division.
#   (7,2): 3.5 vs 3  -> distinguishing;  (6,3): 2 vs 2 and (8,2): 4 vs 4 -> agree.
# problem 1: Python test has no literal candidate calls -> no inputs.
RECORDS = {
    "0": {
        "Python": _rec(
            "def divide(a: int, b: int) -> float:",
            "def divide(a, b):\n    return a / b\n",
            "def check(candidate):\n"
            "    assert candidate(7, 2) == 3.5\n"
            "    assert candidate(6, 3) == 2\n"
            "    assert candidate(8, 2) == 4\n",
        ),
        "C++": _rec(
            "double divide(int a, int b)",
            "double divide(int a, int b){ return a / b; }",
            "",
        ),
    },
    "1": {
        "Python": _rec(
            "def f(x: int) -> int:",
            "def f(x):\n    return x\n",
            "def check(candidate):\n    y = 3\n    assert candidate(y) == y\n",  # no literal
        ),
    },
}


def _analysis(tmp_path):
    cfg = Config.from_dict({
        "data_dir": str(tmp_path),
        "dataset": {"type": "humaneval_x"},
        "languages": ["Python", "C++"],
        "verification": {"run_timeout_seconds": 15, "compile_timeout_seconds": 40},
    })
    a = HumanEvalXAnalysis(cfg)
    a.provider.is_ready = lambda: True
    a.provider.load_records = lambda: RECORDS
    return a


@pytest.mark.skipif(not TOOLCHAINS, reason="gcc + python3 required")
def test_stores_inputs_and_wrappers(tmp_path):
    a = _analysis(tmp_path)
    a.run(workers=1)

    # extracted test inputs stored and correct
    inputs_file = a.inputs_dir / "0.json"
    assert inputs_file.is_file()
    assert json.loads(inputs_file.read_text()) == [[7, 2], [6, 3], [8, 2]]

    # generated wrappers stored, per language, and are non-trivial programs
    py_w = a.wrappers_dir / "0" / "Python.py"
    cpp_w = a.wrappers_dir / "0" / "C++.cpp"
    assert py_w.is_file() and "def divide" in py_w.read_text()
    assert cpp_w.is_file() and "double divide" in cpp_w.read_text()

    # problem 1 has no literal inputs -> stored as empty, recorded as such
    assert json.loads((a.inputs_dir / "1.json").read_text()) == []


@pytest.mark.skipif(not TOOLCHAINS, reason="gcc + python3 required")
def test_counts_distinguishing_inputs(tmp_path):
    a = _analysis(tmp_path)
    summary = a.run(workers=1)

    assert summary["n_problems"] == 2
    assert summary["n_problems_with_inputs"] == 1
    assert summary["n_problems_without_inputs"] == 1
    assert summary["total_test_inputs"] == 3
    assert summary["total_reliable_inputs"] == 3          # both refs clean on all 3
    assert summary["total_distinguishing_inputs"] == 1     # only (7,2)
    assert summary["problems_with_distinguishing_input"] == 1
    assert summary["pair_distinguishing_inputs"] == {"C++|Python": 1}

    # summary.json written and matches
    on_disk = json.loads((a.out_dir / "summary.json").read_text())
    assert on_disk["total_distinguishing_inputs"] == 1

    text = format_analysis(summary)
    assert "distinguishing" in text
    assert "C++|Python" in text


def test_requires_humaneval_x_dataset(tmp_path):
    cfg = Config.from_dict({"data_dir": str(tmp_path), "dataset": {"type": "codenet"}})
    with pytest.raises(ValueError):
        HumanEvalXAnalysis(cfg)

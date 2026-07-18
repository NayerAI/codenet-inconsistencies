"""Tests for reclassification and the reverify command."""

import shutil

import pytest

from codenet_eval.config import Config
from codenet_eval.report import summarise
from codenet_eval.runner import Runner
from codenet_eval.utils import read_jsonl, write_jsonl

TOOLCHAINS = all(shutil.which(b) for b in ("gcc", "python3"))


def _prog(returncode, stdout):
    return {
        "language": "x",
        "ran": True,
        "returncode": returncode,
        "stdout": stdout,
        "stderr": "" if returncode == 0 else "boom",
        "timed_out": False,
    }


def _row(ra, rb, out_a, out_b):
    return {
        "problem_id": "p1",
        "language_a": "C",
        "language_b": "Python",
        "kind": "program",
        "inconsistent": True,
        "divergence_input": "x",
        "verification": {
            "status": "confirmed",  # deliberately (mis)labelled to test recompute
            "method": "programs",
            "input": "x",
            "program_a": _prog(ra, out_a),
            "program_b": _prog(rb, out_b),
        },
    }


def test_reverify_reclassify_only(tmp_path):
    run_dir = tmp_path / "results" / "r"
    run_dir.mkdir(parents=True)
    rows = [
        _row(0, 1, "3", ""),    # B crashed (exit 1) -> must become inconclusive
        _row(0, 0, "3", "4"),   # both clean, both non-empty, differ -> strong
        _row(0, 0, "3", ""),    # both clean but B empty -> confirmed weak
        _row(0, 0, "5", "5"),   # both clean, equal -> refuted
    ]
    write_jsonl(run_dir / "results.jsonl", rows)

    runner = Runner(Config.from_dict({"data_dir": str(tmp_path)}))
    updated, _ = runner.reverify(run_dir, reexecute=False)
    assert updated == 4

    out = list(read_jsonl(run_dir / "results.jsonl"))
    assert out[0]["verification"]["status"] == "inconclusive"
    assert out[1]["verification"]["status"] == "confirmed"
    assert out[1]["verification"]["strong_semantic_diff"] is True
    assert out[2]["verification"]["status"] == "confirmed"
    assert out[2]["verification"]["strong_semantic_diff"] is False
    assert out[3]["verification"]["status"] == "refuted"
    assert (run_dir / "results.jsonl.bak").is_file()   # original backed up

    s = summarise(run_dir)
    assert s["verification"]["confirmed"] == 2
    assert s["verification"]["confirmed_strong"] == 1
    assert s["strong_semantic_differences"] == 1
    assert s["verification"]["inconclusive"] == 1


@pytest.mark.skipif(not TOOLCHAINS, reason="gcc + python3 required")
def test_reverify_reexecute_function_drivers(tmp_path):
    run_dir = tmp_path / "results" / "r"
    run_dir.mkdir(parents=True)
    write_jsonl(run_dir / "manifest.jsonl", [{
        "problem_id": "0",
        "submissions": {
            "Python": {"filename_ext": ".py", "submission_id": "Python/0", "path": "n/a"},
            "C++": {"filename_ext": ".cpp", "submission_id": "CPP/0", "path": "n/a"},
        },
        "pairs": [["Python", "C++"]],
    }])
    write_jsonl(run_dir / "results.jsonl", [{
        "problem_id": "0",
        "language_a": "Python",
        "language_b": "C++",
        "kind": "function",
        "inconsistent": True,
        "divergence_input": "f(7)",
        "program_a": "print(7//2)\n",  # 3
        "program_b": '#include <iostream>\nint main(){std::cout<<7.0/2<<"\\n";}\n',  # 3.5
        "verification": {"status": "skipped", "method": "llm_driver"},
    }])

    runner = Runner(Config.from_dict({"data_dir": str(tmp_path)}))
    runner.reverify(run_dir, reexecute=True)

    v = list(read_jsonl(run_dir / "results.jsonl"))[0]["verification"]
    assert v["method"] == "llm_driver"
    assert v["status"] == "confirmed"
    assert v["strong_semantic_diff"] is True

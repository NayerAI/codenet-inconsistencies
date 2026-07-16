import shutil

import pytest

from codenet_eval.llm import LLMResponse
from codenet_eval.report import summarise
from codenet_eval.runner import Runner
from codenet_eval.utils import read_jsonl

TOOLCHAINS = all(shutil.which(b) for b in ("gcc", "python3"))


class FakeClient:
    """Stub LLM: claims p00001 inconsistent (7/2), p00002 consistent."""

    def __init__(self):
        self.calls = 0

    def complete(self, messages):
        self.calls += 1
        user = messages[1]["content"]
        if "Problem id: p00001" in user:
            parsed = {
                "inconsistent": True,
                "confidence": 0.9,
                "category": "integer_vs_float_division",
                "reasoning": "C/Java truncate, Python keeps the fraction",
                "divergence_input": "7 2\n",
                "expected_output_a": "3",
                "expected_output_b": "3.5",
            }
        else:
            parsed = {
                "inconsistent": False,
                "confidence": 0.8,
                "category": "none",
                "reasoning": "identical sums",
                "divergence_input": None,
            }
        return LLMResponse(raw_content="{}", parsed=parsed, model="fake", usage={"total_tokens": 5})


def test_sample_writes_manifest(mini_config, tmp_path):
    runner = Runner(mini_config)
    run_dir = tmp_path / "run"
    rows = runner.sample(run_dir)
    assert len(rows) == 2
    assert (run_dir / "manifest.jsonl").is_file()
    # Default reference pairing -> two pairs per problem.
    assert rows[0]["pairs"] == [["C", "Python"], ["C", "Java"]]


def test_evaluate_dry_run_makes_no_calls(mini_config, tmp_path):
    runner = Runner(mini_config)
    run_dir = tmp_path / "run"
    runner.sample(run_dir)
    results_path = runner.evaluate(run_dir, client=None)
    results = list(read_jsonl(results_path))
    assert len(results) == 4
    assert all(r.get("dry_run") for r in results)


@pytest.mark.skipif(not TOOLCHAINS, reason="gcc + python3 required for verification")
def test_evaluate_with_fake_client_and_verification(mini_config, tmp_path):
    runner = Runner(mini_config)
    run_dir = tmp_path / "run"
    runner.sample(run_dir)

    client = FakeClient()
    results_path = runner.evaluate(run_dir, client)
    results = list(read_jsonl(results_path))

    assert client.calls == 4  # 2 problems x 2 pairs
    assert len(results) == 4

    by_key = {(r["problem_id"], r["language_a"], r["language_b"]): r for r in results}

    # p00001 C vs Python: LLM says inconsistent, execution confirms (3 vs 3.5).
    cp = by_key[("p00001", "C", "Python")]
    assert cp["inconsistent"] is True
    assert cp["verification"]["status"] == "confirmed"
    assert cp["verification"]["outputs_differ"] is True

    # p00001 C vs Java: both integer-divide, so execution refutes the claim.
    cj = by_key[("p00001", "C", "Java")]
    if shutil.which("javac"):
        assert cj["verification"]["status"] == "refuted"

    # p00002: consistent, no verification attempted.
    assert by_key[("p00002", "C", "Python")]["inconsistent"] is False
    assert "verification" not in by_key[("p00002", "C", "Python")]


@pytest.mark.skipif(not TOOLCHAINS, reason="gcc + python3 required")
def test_resume_skips_completed_pairs(mini_config, tmp_path):
    runner = Runner(mini_config)
    run_dir = tmp_path / "run"
    runner.sample(run_dir)

    first = FakeClient()
    runner.evaluate(run_dir, first)
    assert first.calls == 4

    second = FakeClient()
    runner.evaluate(run_dir, second, resume=True)
    assert second.calls == 0  # everything already done

    summary = summarise(run_dir)
    assert summary["total_requests"] == 4
    assert summary["inconsistent"] == 2  # both p00001 pairs

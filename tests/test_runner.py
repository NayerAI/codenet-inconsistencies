import shutil
import threading

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
        self._lock = threading.Lock()

    def complete(self, messages):
        with self._lock:
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


@pytest.mark.skipif(not TOOLCHAINS, reason="gcc + python3 required")
def test_parallel_evaluation_produces_all_results(mini_config, tmp_path):
    # More pairs than workers, plus real compilation in the verification step,
    # exercises concurrent writes and thread-safety.
    mini_config.pairing.strategy = "all"  # 3 pairs per problem -> 6 total
    runner = Runner(mini_config)
    run_dir = tmp_path / "run"
    runner.sample(run_dir)

    client = FakeClient()
    runner.evaluate(run_dir, client, workers=4)
    results = list(read_jsonl(run_dir / "results.jsonl"))

    assert client.calls == 6
    assert len(results) == 6
    # No pair is written twice despite concurrency.
    keys = {(r["problem_id"], r["language_a"], r["language_b"]) for r in results}
    assert len(keys) == 6

    summary = summarise(run_dir)
    assert summary["total_requests"] == 6
    # p00001 (3 pairs) inconsistent; verification confirms the C/Python-style
    # divergences and refutes the same-integer-semantics ones.
    assert summary["inconsistent"] == 3


def _humaneval_run(tmp_path, stub):
    import gzip
    import json

    from codenet_eval.config import Config

    base = tmp_path / "hex"
    for token, prefix in [("python", "Python"), ("cpp", "CPP")]:
        p = base / token / "data" / f"humaneval_{token}.jsonl.gz"
        p.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(p, "wt", encoding="utf-8") as fh:
            fh.write(json.dumps({"task_id": f"{prefix}/0", "prompt": "def f():\n", "canonical_solution": "    return 1\n"}) + "\n")

    cfg = Config.from_dict({
        "data_dir": str(tmp_path / "data"),
        "dataset": {"type": "humaneval_x", "humaneval_x_base_url": f"file://{base}"},
        "languages": ["Python", "C++"],
        "pairing": {"strategy": "all"},
        "verification": {"enabled": True},
    })
    runner = Runner(cfg)
    runner.provider.ensure()
    run_dir = tmp_path / "run"
    runner.sample(run_dir)
    runner.evaluate(run_dir, stub)
    return run_dir, list(read_jsonl(run_dir / "results.jsonl"))


def test_function_dataset_without_drivers_skips_verification(tmp_path):
    class Stub:
        def complete(self, messages):
            assert "two FUNCTIONS" in messages[0]["content"]        # function prompt
            assert "program_a" in messages[0]["content"]            # drivers requested
            return LLMResponse(raw_content="{}", parsed={"inconsistent": True, "divergence_input": "f()"}, model="s", usage={})

    run_dir, results = _humaneval_run(tmp_path, Stub())
    assert len(results) == 1
    assert results[0]["kind"] == "function"
    assert results[0]["verification"]["status"] == "skipped"  # no drivers returned
    assert summarise(run_dir)["verification"]["skipped"] == 1


@pytest.mark.skipif(not TOOLCHAINS, reason="gcc + python3 required")
def test_function_dataset_driver_verification_confirmed(tmp_path):
    class Stub:
        def complete(self, messages):
            return LLMResponse(
                raw_content="{}",
                parsed={
                    "inconsistent": True,
                    "divergence_input": "f(7)",
                    "program_a": "print(7/2)\n",  # Python -> 3.5
                    "program_b": '#include <iostream>\nint main(){std::cout<<7/2<<"\\n";}\n',  # C++ -> 3
                },
                model="s",
                usage={},
            )

    run_dir, results = _humaneval_run(tmp_path, Stub())
    v = results[0]["verification"]
    assert v["method"] == "llm_driver"
    assert v["status"] == "confirmed"
    assert v["outputs_differ"] is True


def test_workers_config_and_override(mini_config, tmp_path):
    # execution.workers default plus an explicit --workers-style override.
    assert mini_config.execution.workers == 4
    mini_config.execution.workers = 2
    runner = Runner(mini_config)
    run_dir = tmp_path / "run"
    runner.sample(run_dir)
    # workers=1 forces the sequential path; result set must be identical.
    runner.evaluate(run_dir, client=None, workers=1)  # dry-run, no API
    results = list(read_jsonl(run_dir / "results.jsonl"))
    assert len(results) == 4
    assert all(r.get("dry_run") for r in results)

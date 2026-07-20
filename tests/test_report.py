"""Report scoping: a reused run directory must not mix in stale results."""

from codenet_eval.report import summarise
from codenet_eval.utils import write_jsonl


def _res(pid, a, b, inconsistent):
    return {"problem_id": pid, "language_a": a, "language_b": b,
            "inconsistent": inconsistent, "category": "x" if inconsistent else None}


def test_report_scoped_to_current_manifest_and_ignores_dry_rows(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    # Current manifest: 2 problems, one C++/Python pair each.
    write_jsonl(run_dir / "manifest.jsonl", [
        {"problem_id": "p1", "pairs": [["C++", "Python"]]},
        {"problem_id": "p2", "pairs": [["C++", "Python"]]},
    ])
    # results.jsonl accumulated across configs + old dry-run previews:
    write_jsonl(run_dir / "results.jsonl", [
        _res("p1", "C++", "Python", True),                 # current config
        _res("p2", "C++", "Python", False),                # current config
        _res("p9", "C++", "Java", True),                   # stale (other config)
        _res("p8", "Ruby", "Go", True),                    # stale (other config)
        {"problem_id": "p1", "language_a": "C++", "language_b": "Python", "dry_run": True},
    ])

    s = summarise(run_dir)
    assert s["total_requests"] == 2          # only the 2 manifest pairs, no dry rows
    assert s["inconsistent"] == 1
    assert s["consistent"] == 1


def test_report_dedupes_repeated_pair_keeping_last(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_jsonl(run_dir / "manifest.jsonl", [{"problem_id": "p1", "pairs": [["C++", "Python"]]}])
    write_jsonl(run_dir / "results.jsonl", [
        _res("p1", "C++", "Python", True),
        _res("p1", "C++", "Python", False),   # re-run of the same pair -> last wins
    ])
    s = summarise(run_dir)
    assert s["total_requests"] == 1
    assert s["consistent"] == 1 and s["inconsistent"] == 0

"""Aggregate a run's ``results.jsonl`` into summary statistics."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .runner import RESULTS_NAME
from .utils import get_logger, read_jsonl

log = get_logger(__name__)


def summarise(run_dir: Path) -> dict:
    results_path = run_dir / RESULTS_NAME
    if not results_path.is_file():
        raise FileNotFoundError(f"No results found at {results_path}")

    rows = list(read_jsonl(results_path))
    total = len(rows)
    llm_errors = sum(1 for r in rows if r.get("llm_error"))
    parse_errors = sum(1 for r in rows if r.get("parse_error"))
    evaluated = [r for r in rows if not r.get("llm_error") and r.get("inconsistent") is not None]

    inconsistent = [r for r in evaluated if r.get("inconsistent") is True]
    consistent = [r for r in evaluated if r.get("inconsistent") is False]

    categories = Counter(r.get("category") or "unknown" for r in inconsistent)
    pair_counter = Counter(f"{r['language_a']}/{r['language_b']}" for r in rows)

    verifications = [r.get("verification") for r in inconsistent if r.get("verification")]
    verif_status = Counter(v.get("status") for v in verifications)
    confirmed = verif_status.get("confirmed", 0)
    refuted = verif_status.get("refuted", 0)
    verified_total = confirmed + refuted

    tokens = sum((r.get("usage") or {}).get("total_tokens", 0) or 0 for r in rows)

    summary = {
        "run_dir": str(run_dir),
        "total_requests": total,
        "llm_errors": llm_errors,
        "parse_errors": parse_errors,
        "evaluated": len(evaluated),
        "inconsistent": len(inconsistent),
        "consistent": len(consistent),
        "inconsistency_rate": (len(inconsistent) / len(evaluated)) if evaluated else None,
        "categories": dict(categories.most_common()),
        "pairs": dict(pair_counter.most_common()),
        "verification": {
            "attempted": len(verifications),
            "confirmed": confirmed,
            "refuted": refuted,
            "inconclusive": verif_status.get("inconclusive", 0),
            "precision_on_verified": (confirmed / verified_total) if verified_total else None,
        },
        "total_tokens": tokens,
    }
    return summary


def write_summary(run_dir: Path, summary: dict) -> Path:
    out = run_dir / "summary.json"
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def format_summary(summary: dict) -> str:
    v = summary["verification"]
    lines = [
        "==================== CodeNet inconsistency run ====================",
        f"run dir            : {summary['run_dir']}",
        f"total LLM requests : {summary['total_requests']}",
        f"  llm errors       : {summary['llm_errors']}",
        f"  parse errors     : {summary['parse_errors']}",
        f"evaluated (usable) : {summary['evaluated']}",
        f"  inconsistent     : {summary['inconsistent']}",
        f"  consistent       : {summary['consistent']}",
        f"  inconsistency %  : {_pct(summary['inconsistency_rate'])}",
        "verification (of inconsistent claims):",
        f"  attempted        : {v['attempted']}",
        f"  confirmed (differ): {v['confirmed']}",
        f"  refuted (same)   : {v['refuted']}",
        f"  inconclusive     : {v['inconclusive']}",
        f"  precision        : {_pct(v['precision_on_verified'])}",
        f"total tokens       : {summary['total_tokens']}",
    ]
    if summary["categories"]:
        lines.append("top inconsistency categories:")
        for cat, count in list(summary["categories"].items())[:10]:
            lines.append(f"  {cat:24s} {count}")
    lines.append("===================================================================")
    return "\n".join(lines)


def _pct(value) -> str:
    if value is None:
        return "n/a"
    return f"{100.0 * value:.1f}%"

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

    # Strongest evidence of differing semantics: both programs exit 0, both print
    # something, and their outputs differ.
    strong = sum(1 for v in verifications if v.get("strong_semantic_diff"))
    # Among confirmed, how many are "weak" (a clean run that printed nothing).
    confirmed_weak = confirmed - sum(
        1 for v in verifications if v.get("status") == "confirmed" and v.get("strong_semantic_diff")
    )
    # Why checks were inconclusive (which side failed, e.g. "exited 1").
    inconclusive_reasons: Counter = Counter()
    for v in verifications:
        if v.get("status") == "inconclusive":
            for side in (v.get("inconclusive_reason") or {}).values():
                inconclusive_reasons[side] += 1

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
            # 'attempted' counts executed checks (skipped function-level ones excluded).
            "attempted": confirmed + refuted + verif_status.get("inconclusive", 0),
            "confirmed": confirmed,
            "confirmed_strong": strong,
            "confirmed_weak": confirmed_weak,
            "refuted": refuted,
            "inconclusive": verif_status.get("inconclusive", 0),
            "skipped": verif_status.get("skipped", 0),
            "precision_on_verified": (confirmed / verified_total) if verified_total else None,
            "inconclusive_reasons": dict(inconclusive_reasons.most_common(10)),
        },
        "strong_semantic_differences": strong,
        "total_tokens": tokens,
    }
    return summary


def summarise_transpilation(run_dir: Path) -> dict:
    results_path = run_dir / RESULTS_NAME
    if not results_path.is_file():
        raise FileNotFoundError(f"No results found at {results_path}")
    rows = list(read_jsonl(results_path))
    total = len(rows)
    llm_errors = sum(1 for r in rows if r.get("llm_error"))
    evaluated = [r for r in rows if r.get("category")]
    cats = Counter(r.get("category") for r in evaluated)
    pairs = Counter(f"{r['source_language']}->{r['target_language']}" for r in rows)
    # Units that could even show the phenomenon (a distinguishing input exists).
    with_distinguishing = sum(1 for r in evaluated if (r.get("n_distinguishing") or 0) > 0)
    false_neg = cats.get("false_negative", 0)
    tokens = sum((r.get("usage") or {}).get("total_tokens", 0) or 0 for r in rows)
    denom = false_neg + cats.get("relaxed", 0) + cats.get("consistent", 0) + cats.get("incorrect", 0)
    return {
        "run_dir": str(run_dir),
        "experiment": "transpilation",
        "total_units": total,
        "llm_errors": llm_errors,
        "evaluated": len(evaluated),
        "categories": dict(cats.most_common()),
        "false_negatives": false_neg,
        "false_negative_rate": (false_neg / denom) if denom else None,
        "units_with_distinguishing_input": with_distinguishing,
        "pairs": dict(pairs.most_common()),
        "total_tokens": tokens,
    }


def format_transpilation_summary(s: dict) -> str:
    c = s["categories"]
    lines = [
        "==================== transpilation experiment ====================",
        f"run dir            : {s['run_dir']}",
        f"total units        : {s['total_units']}",
        f"  llm errors       : {s['llm_errors']}",
        f"  evaluated        : {s['evaluated']}",
        f"units w/ distinguishing input : {s['units_with_distinguishing_input']}",
        "categories:",
        f"  false_negative (strict source kept, target tests reject): {c.get('false_negative', 0)}",
        f"  relaxed        (matched target semantics)               : {c.get('relaxed', 0)}",
        f"  consistent     (matched both)                           : {c.get('consistent', 0)}",
        f"  incorrect      (matched neither)                        : {c.get('incorrect', 0)}",
        f"  inconclusive   (references not runnable)                : {c.get('inconclusive', 0)}",
        f"false-negative rate : {_pct(s['false_negative_rate'])}",
        f"total tokens        : {s['total_tokens']}",
        "==================================================================",
    ]
    return "\n".join(lines)


def write_summary(run_dir: Path, summary: dict) -> Path:
    out = run_dir / "summary.json"
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def format_summary(summary: dict) -> str:
    v = summary["verification"]
    lines = [
        "================ cross-language inconsistency run =================",
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
        f"    strong (both exit0, both non-empty, differ): {v.get('confirmed_strong', 0)}",
        f"    weak (one side printed nothing)           : {v.get('confirmed_weak', 0)}",
        f"  refuted (same)   : {v['refuted']}",
        f"  inconclusive     : {v['inconclusive']}",
        f"  skipped (func)   : {v.get('skipped', 0)}",
        f"  precision        : {_pct(v['precision_on_verified'])}",
        f"total tokens       : {summary['total_tokens']}",
    ]
    if v.get("inconclusive_reasons"):
        lines.append("inconclusive reasons (per failing side):")
        for reason, count in v["inconclusive_reasons"].items():
            lines.append(f"  {reason:40s} {count}")
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

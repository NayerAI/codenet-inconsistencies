"""Dataset-level analysis for HumanEval-X (no LLM involved).

Two things, both aimed at making the dataset inspectable:

1. **Persist the raw material.** For every problem it writes
   * the concrete test inputs extracted from the Python ``test`` to
     ``data/humaneval-x/analysis/test_inputs/<id>.json`` and
   * the generated stdin/stdout wrapper for each requested language to
     ``data/humaneval-x/analysis/wrappers/<id>/<language><ext>``
   so the exact programs that get executed can be read on disk.

2. **Measure how many test cases are even *different*.** Each language's
   reference wrapper is compiled once and run on every test input; a test input
   is *distinguishing* when the reference implementations, all exiting cleanly,
   produce more than one distinct canonical output. This says how many test
   cases are capable of exposing a cross-language inconsistency at all -- a
   property of the dataset itself, independent of any model.
"""

from __future__ import annotations

import json
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from itertools import combinations
from pathlib import Path
from typing import Optional

from .config import Config
from .harness import UnsupportedSignature, build_wrapper
from .hxtest import parse_test_inputs
from .providers import HumanEvalXProvider, get_provider
from .utils import append_jsonl, get_logger
from .verification import normalise_output, prepare_program

log = get_logger(__name__)

_EXT = {"Python": ".py", "C++": ".cpp", "Java": ".java", "JavaScript": ".js", "Go": ".go"}

PROBLEMS_NAME = "problems.jsonl"
SUMMARY_NAME = "summary.json"


def _code(rec: dict) -> str:
    return (rec.get("prompt", "") or "") + (rec.get("canonical_solution", "") or "")


def _sort_key(pid: str):
    return (0, int(pid)) if pid.isdigit() else (1, pid)


class HumanEvalXAnalysis:
    """Store test inputs + wrappers and measure distinguishing test cases."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        provider = get_provider(cfg)
        if not isinstance(provider, HumanEvalXProvider):
            raise ValueError(
                f"hx-analyze requires dataset.type: humaneval_x (got {cfg.dataset.type!r})"
            )
        self.provider = provider
        self.out_dir = cfg.humaneval_x_root / "analysis"
        self.inputs_dir = self.out_dir / "test_inputs"
        self.wrappers_dir = self.out_dir / "wrappers"

    # -- driver --------------------------------------------------------------
    def run(self, max_problems: Optional[int] = None, workers: Optional[int] = None) -> dict:
        if not self.provider.is_ready():
            raise FileNotFoundError("HumanEval-X not prepared. Run 'download' first.")
        records = self.provider.load_records()
        languages = list(self.cfg.languages)
        workers = max(1, workers if workers is not None else self.cfg.execution.workers)

        self.inputs_dir.mkdir(parents=True, exist_ok=True)
        self.wrappers_dir.mkdir(parents=True, exist_ok=True)
        problems_path = self.out_dir / PROBLEMS_NAME
        if problems_path.exists():
            problems_path.unlink()          # start a fresh analysis run

        items = sorted(records.items(), key=lambda kv: _sort_key(kv[0]))
        if max_problems is not None:
            items = items[:max_problems]

        log.info(
            "Analysing %d HumanEval-X problems for languages %s (%d worker(s))",
            len(items), ", ".join(languages), workers,
        )

        lock = threading.Lock()
        out_records: list[dict] = []

        def handle(item) -> None:
            rec = self._analyse_problem(item[0], item[1], languages)
            if rec is None:
                return
            with lock:
                append_jsonl(problems_path, rec)
                out_records.append(rec)

        if workers == 1:
            for it in items:
                handle(it)
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                list(pool.map(handle, items))

        summary = self._summarise(out_records, languages)
        (self.out_dir / SUMMARY_NAME).write_text(
            json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        log.info("Stored test inputs   -> %s", self.inputs_dir)
        log.info("Stored wrappers      -> %s", self.wrappers_dir)
        log.info("Per-problem analysis -> %s", problems_path)
        log.info("Summary              -> %s", self.out_dir / SUMMARY_NAME)
        return summary

    # -- one problem ---------------------------------------------------------
    def _analyse_problem(self, num: str, by_lang: dict, languages: list[str]) -> Optional[dict]:
        py = by_lang.get("Python")
        if not py:
            return None                     # no Python reference -> nothing to test
        inputs = parse_test_inputs(py.get("test", "") or "")
        # Persist the extracted inputs even when empty, so the absence is visible.
        (self.inputs_dir / f"{num}.json").write_text(
            json.dumps(inputs, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        if not inputs:
            return {
                "problem_id": num, "languages": [], "n_inputs": 0,
                "n_reliable": 0, "n_distinguishing": 0,
                "reason": "no literal test inputs",
                "test_inputs_file": f"test_inputs/{num}.json",
            }

        # Build + store every wrappable language's reference wrapper, compile once.
        progs = {}
        wrapper_files: dict[str, str] = {}
        used: list[str] = []
        wrap_dir = self.wrappers_dir / str(num)
        wrap_dir.mkdir(parents=True, exist_ok=True)
        for lang in languages:
            rec = by_lang.get(lang)
            if rec is None:
                continue
            try:
                wrapped = build_wrapper(lang, _code(rec), rec.get("declaration", "") or "")
            except UnsupportedSignature:
                continue
            path = wrap_dir / f"{lang}{_EXT[lang]}"
            path.write_text(wrapped, encoding="utf-8")
            wrapper_files[lang] = f"wrappers/{num}/{lang}{_EXT[lang]}"
            progs[lang] = prepare_program(lang, wrapped, _EXT[lang], self.cfg.verification)
            used.append(lang)

        n_reliable = n_distinguishing = 0
        pair_diff: Counter = Counter()
        examples: list[dict] = []
        try:
            for args in inputs:
                stdin = "".join(json.dumps(a) + "\n" for a in args)
                outs = {}
                for lang in used:
                    r = progs[lang].run(stdin)
                    if r.clean:
                        outs[lang] = normalise_output(r.stdout)
                if len(outs) < 2:
                    continue                # need >=2 clean references to compare
                n_reliable += 1
                if len(set(outs.values())) > 1:
                    n_distinguishing += 1
                    for a, b in combinations(sorted(outs), 2):
                        if outs[a] != outs[b]:
                            pair_diff[f"{a}|{b}"] += 1
                    if len(examples) < 10:
                        examples.append({"input": args, "outputs": outs})
        finally:
            for p in progs.values():
                p.close()

        return {
            "problem_id": num,
            "languages": used,
            "n_inputs": len(inputs),
            "n_reliable": n_reliable,
            "n_distinguishing": n_distinguishing,
            "pair_distinguishing": dict(pair_diff),
            "distinguishing_examples": examples,
            "wrapper_files": wrapper_files,
            "test_inputs_file": f"test_inputs/{num}.json",
        }

    # -- aggregate -----------------------------------------------------------
    def _summarise(self, records: list[dict], languages: list[str]) -> dict:
        pair_total: Counter = Counter()
        pair_problems: Counter = Counter()
        total_inputs = total_reliable = total_dist = 0
        with_inputs = with_dist = no_inputs = 0
        for r in records:
            n_in = r.get("n_inputs", 0)
            total_inputs += n_in
            total_reliable += r.get("n_reliable", 0)
            total_dist += r.get("n_distinguishing", 0)
            if n_in > 0:
                with_inputs += 1
            else:
                no_inputs += 1
            if r.get("n_distinguishing", 0) > 0:
                with_dist += 1
            for k, v in (r.get("pair_distinguishing") or {}).items():
                pair_total[k] += v
                pair_problems[k] += 1
        return {
            "dataset": "humaneval_x",
            "languages": languages,
            "n_problems": len(records),
            "n_problems_with_inputs": with_inputs,
            "n_problems_without_inputs": no_inputs,
            "total_test_inputs": total_inputs,
            "total_reliable_inputs": total_reliable,
            "total_distinguishing_inputs": total_dist,
            "problems_with_distinguishing_input": with_dist,
            "distinguishing_input_rate": round(total_dist / total_reliable, 4) if total_reliable else 0.0,
            "pair_distinguishing_inputs": dict(pair_total.most_common()),
            "pair_distinguishing_problems": dict(pair_problems.most_common()),
            "output_dir": str(self.out_dir),
        }


def format_analysis(summary: dict) -> str:
    lines = [
        "================ HumanEval-X test-case analysis ================",
        f"languages                     : {', '.join(summary['languages'])}",
        f"problems analysed             : {summary['n_problems']}",
        f"  with literal test inputs    : {summary['n_problems_with_inputs']}",
        f"  without literal test inputs : {summary['n_problems_without_inputs']}",
        f"test inputs (total)           : {summary['total_test_inputs']}",
        f"  comparable (>=2 clean refs) : {summary['total_reliable_inputs']}",
        f"  distinguishing              : {summary['total_distinguishing_inputs']}"
        f"  ({summary['distinguishing_input_rate']:.1%} of comparable)",
        f"problems w/ >=1 distinguishing: {summary['problems_with_distinguishing_input']}",
    ]
    pairs = summary.get("pair_distinguishing_inputs") or {}
    if pairs:
        lines.append("distinguishing inputs by language pair:")
        for pair, n in pairs.items():
            probs = (summary.get("pair_distinguishing_problems") or {}).get(pair, 0)
            lines.append(f"  {pair:24s} {n:6d} inputs across {probs} problems")
    lines.append(f"artifacts under               : {summary['output_dir']}")
    lines.append("===============================================================")
    return "\n".join(lines)

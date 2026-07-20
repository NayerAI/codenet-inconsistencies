"""Transpilation false-negative experiment for HumanEval-X.

For a sampled subset of ``(problem, source_language, target_language)`` triples
we ask the LLM to translate the source snippet to the target language while
*exactly* preserving semantics, then check the translation against the target
and the source reference on the problem's test inputs:

    passes_target  passes_source   category
    -------------  -------------   ---------------------------------------
    yes            yes             consistent  (no divergence on these inputs)
    yes            no              relaxed     (matched target/relaxed semantics)
    no             yes             false_negative  (strict source semantics kept,
                                                    but the target tests reject it)
    no             no              incorrect

"pass" means the translated function reproduces that reference's canonical
output on every (reliable) test input.  Reference outputs are computed by
executing the wrapped reference implementations, so cross-language output
differences are compared on equal, canonical footing.
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from .config import Config
from .harness import UnsupportedSignature, build_wrapper
from .hxtest import parse_test_inputs
from .llm import LLMError, OpenRouterClient
from .prompts import build_transpile_messages, extract_code
from .providers import get_provider
from .runner import MANIFEST_NAME, RESULTS_NAME, _now
from .sampling import select_problem_ids
from .utils import append_jsonl, get_logger, read_jsonl, write_jsonl
from .verification import normalise_output, run_program

log = get_logger(__name__)

_EXT = {"Python": ".py", "C++": ".cpp", "Java": ".java", "JavaScript": ".js", "Go": ".go"}


def _code(rec: dict) -> str:
    return (rec.get("prompt", "") or "") + (rec.get("canonical_solution", "") or "")


class TranspilationRunner:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.provider = get_provider(cfg)

    # --- stage 1: sampling ---------------------------------------------------
    def sample(self, run_dir: Path) -> list[dict]:
        if not self.provider.is_ready():
            raise FileNotFoundError("HumanEval-X not prepared. Run 'download' first.")
        records = self.provider.load_records()
        languages = self.cfg.languages
        max_inputs = self.cfg.experiment.max_test_inputs
        log.info("Building transpilation units for languages: %s", ", ".join(languages))

        units: list[dict] = []
        for num, by_lang in records.items():
            py = by_lang.get("Python")
            if not py:
                continue
            inputs = parse_test_inputs(py.get("test", "") or "", max_inputs=max_inputs)
            if not inputs:
                continue
            for src in languages:
                for tgt in languages:
                    if src == tgt or src not in by_lang or tgt not in by_lang:
                        continue
                    src_rec, tgt_rec = by_lang[src], by_lang[tgt]
                    # Require both reference wrappers to be buildable so we can
                    # compute oracle outputs deterministically.
                    if not (_buildable(src, src_rec) and _buildable(tgt, tgt_rec)):
                        continue
                    units.append({
                        "problem_id": num,
                        "source_language": src,
                        "target_language": tgt,
                        "test_inputs": inputs,
                        "source_code": _code(src_rec),
                        "source_declaration": src_rec.get("declaration", "") or "",
                        "target_declaration": tgt_rec.get("declaration", "") or "",
                        "target_ref_code": _code(tgt_rec),
                    })

        log.info("Found %d evaluable transpilation units", len(units))
        if not units:
            raise RuntimeError("No evaluable transpilation units (check languages / data).")

        keys = [f"{u['problem_id']}|{u['source_language']}|{u['target_language']}" for u in units]
        chosen = set(select_problem_ids(
            keys, percent=self.cfg.sampling.percent, seed=self.cfg.sampling.seed,
            max_samples=self.cfg.sampling.max_samples,
        ))
        rows = [u for u, k in zip(units, keys) if k in chosen]

        run_dir.mkdir(parents=True, exist_ok=True)
        write_jsonl(run_dir / MANIFEST_NAME, rows)
        log.info("Wrote manifest with %d units -> %d LLM calls", len(rows), len(rows))
        return rows

    def dry_run(self, run_dir: Path) -> tuple[int, int]:
        """Count sampled units and planned LLM calls (one per unit); build each
        prompt as a sanity check. Writes nothing; ignores results."""
        manifest = list(read_jsonl(run_dir / MANIFEST_NAME))
        for u in manifest:
            build_transpile_messages(
                u["source_language"], u["source_code"],
                u["target_language"], u["target_declaration"])
        return len(manifest), len(manifest)

    # --- stage 2: evaluation -------------------------------------------------
    def evaluate(
        self,
        run_dir: Path,
        client: Optional[OpenRouterClient],
        limit: Optional[int] = None,
        resume: bool = True,
        workers: Optional[int] = None,
    ) -> Path:
        manifest = list(read_jsonl(run_dir / MANIFEST_NAME))
        results_path = run_dir / RESULTS_NAME
        done = _done_keys(results_path) if resume else set()

        pending = [u for u in manifest
                   if f"{u['problem_id']}|{u['source_language']}|{u['target_language']}" not in done]
        if limit is not None:
            pending = pending[:limit]
        workers = max(1, workers if workers is not None else self.cfg.execution.workers)
        if not pending:
            log.info("Nothing to evaluate (all %d units already done)", len(done))
            return results_path

        log.info("Evaluating %d transpilation units with %d worker(s)", len(pending), workers)
        lock = threading.Lock()

        def handle(unit: dict) -> None:
            row = self._evaluate_unit(unit, client)
            with lock:
                append_jsonl(results_path, row)
                self._log(row)

        if workers == 1:
            for u in pending:
                handle(u)
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                list(pool.map(handle, pending))
        log.info("Evaluation finished: %d units -> %s", len(pending), results_path)
        return results_path

    def _evaluate_unit(self, unit: dict, client: Optional[OpenRouterClient]) -> dict:
        src, tgt = unit["source_language"], unit["target_language"]
        messages = build_transpile_messages(
            src, unit["source_code"], tgt, unit["target_declaration"])

        row = {
            "problem_id": unit["problem_id"],
            "source_language": src,
            "target_language": tgt,
            "model": self.cfg.llm.model,
            "timestamp": _now(),
            "n_inputs": len(unit["test_inputs"]),
        }
        if client is None:
            row["dry_run"] = True
            row["prompt_chars"] = sum(len(m["content"]) for m in messages)
            return row

        try:
            response = client.complete(messages, json_object=False)
        except LLMError as exc:
            row["llm_error"] = str(exc)
            return row
        generated = extract_code(response.raw_content)
        row["generated_code"] = generated[:8000]
        row["usage"] = response.usage

        row.update(self._classify(unit, generated))
        return row

    def _classify(self, unit: dict, generated: str) -> dict:
        src, tgt = unit["source_language"], unit["target_language"]
        vcfg = self.cfg.verification
        # Build the three wrapped programs.
        try:
            gen_w = build_wrapper(tgt, generated, unit["target_declaration"])
        except UnsupportedSignature as exc:
            return {"category": "incorrect", "reason": f"generated code not wrappable: {exc}",
                    "passes_target": False, "passes_source": False}
        src_w = build_wrapper(src, unit["source_code"], unit["source_declaration"])
        tgt_w = build_wrapper(tgt, unit["target_ref_code"], unit["target_declaration"])

        n_reliable = n_distinguishing = 0
        all_match_t = all_match_s = True
        mismatches = []
        for args in unit["test_inputs"]:
            stdin = "".join(json.dumps(a) + "\n" for a in args)
            g = run_program(tgt, gen_w, _EXT[tgt], stdin, vcfg)
            s = run_program(src, src_w, _EXT[src], stdin, vcfg)
            t = run_program(tgt, tgt_w, _EXT[tgt], stdin, vcfg)
            if not (s.clean and t.clean):
                continue  # reference unreliable on this input
            n_reliable += 1
            s_out, t_out = normalise_output(s.stdout), normalise_output(t.stdout)
            if s_out != t_out:
                n_distinguishing += 1
            g_out = normalise_output(g.stdout) if g.clean else None
            match_t = g.clean and g_out == t_out
            match_s = g.clean and g_out == s_out
            all_match_t = all_match_t and match_t
            all_match_s = all_match_s and match_s
            if (not match_t or not match_s) and len(mismatches) < 5:
                mismatches.append({"input": args, "gen": g_out, "source_ref": s_out, "target_ref": t_out})

        if n_reliable == 0:
            return {"category": "inconclusive", "reason": "references not runnable on any input",
                    "passes_target": None, "passes_source": None,
                    "n_reliable": 0, "n_distinguishing": 0}

        passes_target = all_match_t
        passes_source = all_match_s
        category = {
            (True, True): "consistent",
            (True, False): "relaxed",
            (False, True): "false_negative",
            (False, False): "incorrect",
        }[(passes_target, passes_source)]
        return {
            "category": category,
            "passes_target": passes_target,
            "passes_source": passes_source,
            "n_reliable": n_reliable,
            "n_distinguishing": n_distinguishing,
            "mismatches": mismatches,
        }

    def _log(self, row: dict) -> None:
        pair = f"{row['source_language']}->{row['target_language']}"
        if row.get("dry_run"):
            log.info("[dry-run] %s %s", row["problem_id"], pair)
        elif row.get("llm_error"):
            log.warning("%s %s LLM error: %s", row["problem_id"], pair, row["llm_error"])
        else:
            log.info("%s %s -> %s (distinguishing inputs=%s)",
                     row["problem_id"], pair, row.get("category"), row.get("n_distinguishing"))


def _buildable(language: str, rec: dict) -> bool:
    try:
        build_wrapper(language, _code(rec), rec.get("declaration", "") or "")
        return True
    except UnsupportedSignature:
        return False


def _done_keys(results_path: Path) -> set:
    if not results_path.is_file():
        return set()
    keys = set()
    for r in read_jsonl(results_path):
        if r.get("dry_run"):
            continue  # dry-run previews never count as completed work
        if {"problem_id", "source_language", "target_language"} <= r.keys():
            keys.add(f"{r['problem_id']}|{r['source_language']}|{r['target_language']}")
    return keys

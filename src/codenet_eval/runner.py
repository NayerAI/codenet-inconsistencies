"""Orchestration: sample -> query the LLM per language pair -> (verify) -> store.

The pipeline is split into two persisted stages so long runs are reproducible
and resumable:

* ``sample`` writes ``manifest.jsonl`` (the selected problems, their chosen
  submissions and the language pairs to compare).
* ``evaluate`` consumes the manifest, calls the LLM for each pair, optionally
  verifies the proposed input, and appends to ``results.jsonl``.  Re-running
  ``evaluate`` skips pairs already present in ``results.jsonl``.
"""

from __future__ import annotations

import datetime as _dt
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Iterator, Optional

from .config import Config
from .llm import LLMError, OpenRouterClient
from .pairing import language_pairs
from .prompts import build_messages
from .providers import ProblemSample, get_provider
from .sampling import select_problem_ids
from .utils import append_jsonl, get_logger, read_jsonl, write_jsonl
from .verification import verify_divergence, verify_function_divergence

log = get_logger(__name__)

MANIFEST_NAME = "manifest.jsonl"
RESULTS_NAME = "results.jsonl"
CONFIG_SNAPSHOT = "config.snapshot.yaml"


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def default_run_name() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("run-%Y%m%d-%H%M%S")


class Runner:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.provider = get_provider(cfg)

    # --- stage 1: sampling ---------------------------------------------------
    def sample(self, run_dir: Path) -> list[dict]:
        if not self.provider.is_ready():
            raise FileNotFoundError(
                f"Dataset '{self.cfg.dataset.type}' not prepared. Run 'download' first."
            )
        languages = self.cfg.languages
        log.info(
            "Scanning %s problems eligible for languages: %s",
            self.cfg.dataset.type,
            ", ".join(languages),
        )

        eligible: dict[str, ProblemSample] = {
            s.problem_id: s for s in self.provider.iter_eligible(languages)
        }
        log.info("Found %d eligible problems", len(eligible))
        if not eligible:
            avail = ", ".join(self.provider.available_languages())
            raise RuntimeError(
                "No problem is solved in all selected languages "
                f"({', '.join(languages)}). This dataset provides: {avail}. "
                "Run 'inspect' to diagnose; check the 'languages' config."
            )

        chosen_ids = select_problem_ids(
            list(eligible.keys()),
            percent=self.cfg.sampling.percent,
            seed=self.cfg.sampling.seed,
            max_samples=self.cfg.sampling.max_samples,
        )

        pairs = language_pairs(
            languages,
            strategy=self.cfg.pairing.strategy,
            reference_language=self.cfg.pairing.reference_language,
        )
        log.info("Language pairs per problem (%s): %s", self.cfg.pairing.strategy, pairs)

        rows: list[dict] = []
        for pid in chosen_ids:
            sample = eligible[pid]
            self.provider.enrich(sample)  # description / sample I/O for chosen only
            rows.append(
                {
                    "problem_id": pid,
                    "dataset": self.cfg.dataset.type,
                    "description": sample.description,
                    "sample_input": sample.sample_input,
                    "sample_output": sample.sample_output,
                    "submissions": {
                        lang: {
                            "submission_id": unit.unit_id,
                            "language": unit.language,
                            "filename_ext": unit.ext,
                            "kind": unit.kind,
                            "path": str(unit.path),
                        }
                        for lang, unit in sample.units.items()
                    },
                    "pairs": [list(p) for p in pairs],
                }
            )

        run_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = run_dir / MANIFEST_NAME
        write_jsonl(manifest_path, rows)
        total_requests = len(rows) * len(pairs)
        log.info(
            "Wrote manifest with %d problems -> %d LLM requests: %s",
            len(rows),
            total_requests,
            manifest_path,
        )
        return rows

    def load_manifest(self, run_dir: Path) -> list[dict]:
        manifest_path = run_dir / MANIFEST_NAME
        if not manifest_path.is_file():
            raise FileNotFoundError(f"Manifest not found: {manifest_path}. Run 'sample' first.")
        return list(read_jsonl(manifest_path))

    # --- stage 2: evaluation -------------------------------------------------
    def _iter_pairs(self, manifest: list[dict]) -> Iterator[tuple[dict, str, str]]:
        for row in manifest:
            for pair in row["pairs"]:
                yield row, pair[0], pair[1]

    def _existing_keys(self, results_path: Path) -> set[str]:
        if not results_path.is_file():
            return set()
        keys = set()
        for row in read_jsonl(results_path):
            keys.add(_pair_key(row["problem_id"], row["language_a"], row["language_b"]))
        return keys

    def evaluate(
        self,
        run_dir: Path,
        client: Optional[OpenRouterClient],
        limit: Optional[int] = None,
        resume: bool = True,
        workers: Optional[int] = None,
    ) -> Path:
        manifest = self.load_manifest(run_dir)
        results_path = run_dir / RESULTS_NAME
        done = self._existing_keys(results_path) if resume else set()
        if done:
            log.info("Resuming: %d pairs already completed", len(done))

        # Assemble the pending work (pairs not yet done), honouring the limit.
        pending: list[tuple[dict, str, str]] = []
        for mrow, lang_a, lang_b in self._iter_pairs(manifest):
            if _pair_key(mrow["problem_id"], lang_a, lang_b) in done:
                continue
            pending.append((mrow, lang_a, lang_b))
        if limit is not None:
            pending = pending[:limit]

        workers = max(1, workers if workers is not None else self.cfg.execution.workers)
        if not pending:
            log.info("Nothing to evaluate (all %d pairs already done)", len(done))
            return results_path

        log.info("Evaluating %d pairs with %d worker(s)", len(pending), workers)
        write_lock = threading.Lock()

        def handle(task: tuple[dict, str, str]) -> None:
            mrow, lang_a, lang_b = task
            row = self._safe_evaluate_pair(mrow, lang_a, lang_b, client)
            with write_lock:
                append_jsonl(results_path, row)
                self._log_pair_result(row)

        if workers == 1:
            for task in pending:
                handle(task)
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                # list() forces us to surface any unexpected worker exception.
                list(pool.map(handle, pending))

        log.info("Evaluation finished: %d new results -> %s", len(pending), results_path)
        return results_path

    def _safe_evaluate_pair(self, mrow: dict, lang_a: str, lang_b: str, client) -> dict:
        """Never raise: a worker crash must not abort the whole pool/run."""
        try:
            return self._evaluate_pair(mrow, lang_a, lang_b, client)
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("Unexpected error evaluating %s %s/%s", mrow.get("problem_id"), lang_a, lang_b)
            subs = mrow.get("submissions", {})
            return {
                "problem_id": mrow.get("problem_id"),
                "language_a": lang_a,
                "language_b": lang_b,
                "submission_a": subs.get(lang_a, {}).get("submission_id"),
                "submission_b": subs.get(lang_b, {}).get("submission_id"),
                "model": self.cfg.llm.model,
                "timestamp": _now(),
                "error": f"{type(exc).__name__}: {exc}",
            }

    def _evaluate_pair(
        self,
        mrow: dict,
        lang_a: str,
        lang_b: str,
        client: Optional[OpenRouterClient],
    ) -> dict:
        pid = mrow["problem_id"]
        submissions = mrow["submissions"]
        sub_a = submissions[lang_a]
        sub_b = submissions[lang_b]
        code_a = _read_source(Path(sub_a["path"]), self.cfg.llm.max_code_chars)
        code_b = _read_source(Path(sub_b["path"]), self.cfg.llm.max_code_chars)
        # Program vs. function drives both the prompt and whether we verify.
        kind = sub_a.get("kind", "program")
        # For function datasets we ask the LLM for runnable driver programs so we
        # can verify by execution (there is no stdin/stdout harness otherwise).
        request_drivers = (
            kind == "function"
            and self.cfg.verification.enabled
            and self.cfg.verification.function_drivers
        )

        description = sample_in = sample_out = None
        if self.cfg.llm.include_problem_description:
            description = mrow.get("description")
            sample_in = mrow.get("sample_input")
            sample_out = mrow.get("sample_output")

        messages = build_messages(
            problem_id=pid,
            language_a=lang_a,
            code_a=code_a,
            language_b=lang_b,
            code_b=code_b,
            description=description,
            sample_input=sample_in,
            sample_output=sample_out,
            unit_kind=kind,
            request_drivers=request_drivers,
        )

        row: dict = {
            "problem_id": pid,
            "dataset": mrow.get("dataset", self.cfg.dataset.type),
            "language_a": lang_a,
            "submission_a": sub_a["submission_id"],
            "language_b": lang_b,
            "submission_b": sub_b["submission_id"],
            "kind": kind,
            "pairing_strategy": self.cfg.pairing.strategy,
            "model": self.cfg.llm.model,
            "timestamp": _now(),
        }

        if client is None:  # dry run: preview only
            row["dry_run"] = True
            row["prompt_chars"] = sum(len(m["content"]) for m in messages)
            return row

        try:
            response = client.complete(messages)
        except LLMError as exc:
            row["llm_error"] = str(exc)
            return row

        parsed = response.parsed
        row.update(
            {
                "inconsistent": parsed.get("inconsistent"),
                "confidence": parsed.get("confidence"),
                "category": parsed.get("category"),
                "reasoning": parsed.get("reasoning"),
                "divergence_input": parsed.get("divergence_input"),
                "expected_output_a": parsed.get("expected_output_a"),
                "expected_output_b": parsed.get("expected_output_b"),
                "usage": response.usage,
                "parse_error": response.error,
            }
        )

        if kind == "function":
            # Keep the LLM-authored driver programs for auditability.
            row["program_a"] = parsed.get("program_a")
            row["program_b"] = parsed.get("program_b")

        if parsed.get("inconsistent") and parsed.get("divergence_input") is not None:
            if kind == "program" and self.cfg.verification.enabled:
                row["verification"] = verify_divergence(
                    self.cfg.verification,
                    language_a=lang_a,
                    source_a=code_a,
                    ext_a=sub_a["filename_ext"],
                    language_b=lang_b,
                    source_b=code_b,
                    ext_b=sub_b["filename_ext"],
                    divergence_input=str(parsed.get("divergence_input")),
                )
            elif kind == "function" and self.cfg.verification.enabled and self.cfg.verification.function_drivers:
                row["verification"] = verify_function_divergence(
                    self.cfg.verification,
                    language_a=lang_a,
                    program_a=parsed.get("program_a"),
                    ext_a=sub_a["filename_ext"],
                    language_b=lang_b,
                    program_b=parsed.get("program_b"),
                    ext_b=sub_b["filename_ext"],
                    divergence_input=parsed.get("divergence_input"),
                )
            elif kind == "function":
                row["verification"] = {
                    "status": "skipped",
                    "reason": "function verification disabled (verification.function_drivers=false)",
                }
        return row

    def _log_pair_result(self, row: dict) -> None:
        pid = row["problem_id"]
        pair = f"{row['language_a']}/{row['language_b']}"
        if row.get("dry_run"):
            log.info("[dry-run] %s %s (%d prompt chars)", pid, pair, row.get("prompt_chars", 0))
            return
        if row.get("llm_error"):
            log.warning("%s %s -> LLM error: %s", pid, pair, row["llm_error"])
            return
        verdict = row.get("inconsistent")
        verif = (row.get("verification") or {}).get("status")
        log.info(
            "%s %s -> inconsistent=%s confidence=%s%s",
            pid,
            pair,
            verdict,
            row.get("confidence"),
            f" verification={verif}" if verif else "",
        )


def _pair_key(pid: str, lang_a: str, lang_b: str) -> str:
    return f"{pid}|{lang_a}|{lang_b}"


def _read_source(path: Path, max_chars: int) -> str:
    from .utils import read_text_best_effort

    if not path.is_file():
        return f"/* source file missing: {path} */"
    return read_text_best_effort(path, max_chars=max_chars)

"""Read the extracted CodeNet tree: metadata, submissions, descriptions, I/O.

CodeNet layout (after extraction)::

    Project_CodeNet/
      data/<problem_id>/<language>/<submission_id><ext>
      metadata/problem_list.csv
      metadata/<problem_id>.csv
      problem_descriptions/<problem_id>.html
      derived/input_output/data/<problem_id>/{input,output}.txt

Per-problem CSV columns::

    submission_id, problem_id, user_id, date, language, original_language,
    filename_ext, status, cpu_time, memory, code_size, accuracy
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

from .config import Config
from .utils import get_logger, read_text_best_effort

log = get_logger(__name__)

ACCEPTED_STATUS = "Accepted"


@dataclass(frozen=True)
class Submission:
    submission_id: str
    problem_id: str
    language: str
    filename_ext: str
    status: str
    code_size: int
    path: Path

    @property
    def accepted(self) -> bool:
        return self.status == ACCEPTED_STATUS


class CodeNetDataset:
    """Thin read-only accessor over an extracted CodeNet tree."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.root = cfg.dataset_root
        self.data_dir = self.root / "data"
        self.metadata_dir = self.root / "metadata"
        self.descriptions_dir = self.root / "problem_descriptions"
        self.io_dir = self.root / "derived" / "input_output" / "data"

    # --- discovery -----------------------------------------------------------
    def exists(self) -> bool:
        return self.metadata_dir.is_dir()

    def list_problem_ids(self) -> list[str]:
        """All problem ids, taken from the per-problem metadata CSV files."""
        if not self.metadata_dir.is_dir():
            raise FileNotFoundError(
                f"metadata directory missing: {self.metadata_dir}. Run 'download'."
            )
        ids = []
        for csv_path in sorted(self.metadata_dir.glob("*.csv")):
            if csv_path.stem == "problem_list":
                continue
            ids.append(csv_path.stem)
        return ids

    def problem_csv_path(self, problem_id: str) -> Path:
        return self.metadata_dir / f"{problem_id}.csv"

    # --- submissions ---------------------------------------------------------
    def read_submissions(self, problem_id: str) -> list[Submission]:
        csv_path = self.problem_csv_path(problem_id)
        if not csv_path.is_file():
            return []
        submissions: list[Submission] = []
        with open(csv_path, newline="", encoding="utf-8", errors="replace") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                language = (row.get("language") or "").strip()
                sub_id = (row.get("submission_id") or "").strip()
                ext = (row.get("filename_ext") or "").strip()
                if not (language and sub_id and ext):
                    continue
                try:
                    code_size = int(row.get("code_size") or 0)
                except ValueError:
                    code_size = 0
                path = self.data_dir / problem_id / language / f"{sub_id}{ext}"
                submissions.append(
                    Submission(
                        submission_id=sub_id,
                        problem_id=problem_id,
                        language=language,
                        filename_ext=ext,
                        status=(row.get("status") or "").strip(),
                        code_size=code_size,
                        path=path,
                    )
                )
        return submissions

    def representative_for_language(
        self,
        submissions: list[Submission],
        language: str,
        require_accepted: bool = True,
    ) -> Optional[Submission]:
        """Pick one canonical submission for ``language``.

        We prefer the smallest ``Accepted`` submission (compact, likely clean),
        tie-broken by submission id for determinism, and require the source file
        to actually exist on disk.
        """
        candidates = [
            s
            for s in submissions
            if s.language == language
            and (s.accepted or not require_accepted)
            and s.path.is_file()
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda s: (s.code_size if s.code_size > 0 else 1 << 30, s.submission_id))
        return candidates[0]

    def representatives(
        self,
        problem_id: str,
        languages: list[str],
        require_accepted: bool = True,
    ) -> Optional[dict[str, Submission]]:
        """Return one submission per language, or ``None`` if any is missing."""
        submissions = self.read_submissions(problem_id)
        if not submissions:
            return None
        reps: dict[str, Submission] = {}
        for language in languages:
            rep = self.representative_for_language(submissions, language, require_accepted)
            if rep is None:
                return None
            reps[language] = rep
        return reps

    def eligible_problems(
        self,
        languages: list[str],
        require_accepted: bool = True,
        problem_ids: Optional[list[str]] = None,
    ) -> Iterator[tuple[str, dict[str, Submission]]]:
        """Yield ``(problem_id, representatives)`` for every problem that has a
        (preferably accepted) submission in *all* requested languages."""
        ids = problem_ids if problem_ids is not None else self.list_problem_ids()
        for pid in ids:
            reps = self.representatives(pid, languages, require_accepted)
            if reps is not None:
                yield pid, reps

    # --- auxiliary data ------------------------------------------------------
    def read_source(self, submission: Submission, max_chars: int | None = None) -> str:
        return read_text_best_effort(submission.path, max_chars=max_chars)

    def problem_description(self, problem_id: str, max_chars: int = 4000) -> Optional[str]:
        """Return the plain-text problem statement, if available."""
        html_path = self.descriptions_dir / f"{problem_id}.html"
        if not html_path.is_file():
            return None
        html = read_text_best_effort(html_path)
        text = _html_to_text(html)
        if len(text) > max_chars:
            text = text[:max_chars] + " ..."
        return text

    def sample_io(self, problem_id: str, max_chars: int = 2000) -> Optional[tuple[str, str]]:
        """Return a ``(input, output)`` example from the derived I/O, if present."""
        in_path = self.io_dir / problem_id / "input.txt"
        out_path = self.io_dir / problem_id / "output.txt"
        if not (in_path.is_file() and out_path.is_file()):
            return None
        sample_in = read_text_best_effort(in_path, max_chars=max_chars)
        sample_out = read_text_best_effort(out_path, max_chars=max_chars)
        return sample_in, sample_out


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t]+")


def _html_to_text(html: str) -> str:
    """Very small HTML -> text reduction (no external dependencies)."""
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>", "\n", html)
    html = re.sub(r"(?i)</(p|div|li|tr|h[1-6])>", "\n", html)
    text = _TAG_RE.sub(" ", html)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
        .replace("&quot;", '"')
    )
    lines = [_WS_RE.sub(" ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()

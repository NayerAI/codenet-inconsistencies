"""Dataset providers: a uniform interface over CodeNet, TransCoder-test and
HumanEval-X.

Each provider knows how to (a) download/prepare its data and (b) yield problems
that are solved in *all* requested languages, one representative source unit per
language.  The runner then samples, prompts the LLM and (for stdin/stdout
programs) verifies -- identically regardless of the underlying dataset.

Source units come in two ``kind``s:

* ``program``  -- a full stdin/stdout program (CodeNet). Execution-verifiable.
* ``function`` -- a standalone function/snippet (TransCoder, HumanEval-X).
  The LLM is asked for diverging *arguments*; execution-verification is skipped
  (no cross-language calling harness).
"""

from __future__ import annotations

import gzip
import json
import tarfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

from .config import Config
from .dataset import CodeNetDataset
from .download import _is_within, download_url, ensure_dataset
from .utils import get_logger

log = get_logger(__name__)


@dataclass
class SourceUnit:
    language: str          # canonical language label, e.g. "C++", "Python"
    path: Path             # source file on disk
    ext: str               # ".cpp", ".py", ...
    kind: str              # "program" | "function"
    unit_id: str           # submission / task / function id


@dataclass
class ProblemSample:
    problem_id: str
    units: dict[str, SourceUnit]
    description: Optional[str] = None
    sample_input: Optional[str] = None
    sample_output: Optional[str] = None


class DatasetProvider:
    """Common interface implemented by every dataset adapter."""

    type: str = ""
    unit_kind: str = "program"

    def ensure(self, offline: bool = False, force: bool = False) -> None:
        raise NotImplementedError

    def is_ready(self) -> bool:
        raise NotImplementedError

    def available_languages(self) -> list[str]:
        raise NotImplementedError

    def iter_eligible(self, languages: list[str]) -> Iterator[ProblemSample]:
        raise NotImplementedError

    def enrich(self, sample: ProblemSample) -> None:
        """Fill in optional description / sample I/O for a *chosen* sample.

        Called only for sampled problems, so per-dataset heavy lookups (reading
        HTML descriptions etc.) are not paid for the whole eligible set.
        """
        return None


# --------------------------------------------------------------------------- #
# CodeNet
# --------------------------------------------------------------------------- #
class CodeNetProvider(DatasetProvider):
    type = "codenet"
    unit_kind = "program"

    # Informational only (CodeNet has ~55 languages); 'inspect' scans for real.
    COMMON_LANGUAGES = ["C", "C++", "Python", "Java", "Go", "Ruby", "C#", "JavaScript", "PHP"]

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.ds = CodeNetDataset(cfg)

    def ensure(self, offline: bool = False, force: bool = False) -> None:
        ensure_dataset(self.cfg, force=force, offline=offline)

    def is_ready(self) -> bool:
        return self.ds.exists()

    def available_languages(self) -> list[str]:
        return self.COMMON_LANGUAGES

    def iter_eligible(self, languages: list[str]) -> Iterator[ProblemSample]:
        for pid, reps in self.ds.eligible_problems(
            languages, require_accepted=self.cfg.sampling.require_accepted
        ):
            units = {
                lang: SourceUnit(
                    language=lang,
                    path=sub.path,
                    ext=sub.filename_ext,
                    kind="program",
                    unit_id=sub.submission_id,
                )
                for lang, sub in reps.items()
            }
            yield ProblemSample(problem_id=pid, units=units)

    def enrich(self, sample: ProblemSample) -> None:
        if self.cfg.llm.include_problem_description:
            sample.description = self.ds.problem_description(sample.problem_id)
        io = self.ds.sample_io(sample.problem_id)
        if io is not None:
            sample.sample_input, sample.sample_output = io


# --------------------------------------------------------------------------- #
# TransCoder-test (parallel GeeksForGeeks functions in facebookresearch/CodeGen)
# --------------------------------------------------------------------------- #
class TransCoderProvider(DatasetProvider):
    type = "transcoder"
    unit_kind = "function"

    # canonical -> (archive sub-directory, file extension)
    LANG = {"C++": ("cpp", ".cpp"), "Java": ("java", ".java"), "Python": ("python", ".py")}

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.root = cfg.transcoder_root
        self.gfg = self.root / "gfg"                 # gfg/{cpp,java,python}/<ID>.<ext>
        self.archive = self.root / "codegen_repo.tar.gz"

    def available_languages(self) -> list[str]:
        return list(self.LANG)

    def is_ready(self) -> bool:
        return all((self.gfg / d).is_dir() for d, _ in self.LANG.values())

    def ensure(self, offline: bool = False, force: bool = False) -> None:
        if self.is_ready() and not force:
            log.info("TransCoder data already present at %s", self.gfg)
            return
        src = download_url(self.cfg.dataset.transcoder_url, self.archive, offline=offline, force=force)
        self._extract_subdir(src)

    def _extract_subdir(self, archive: Path) -> None:
        subdir = self.cfg.dataset.transcoder_subdir.strip("/")
        needle = "/" + subdir + "/"
        self.gfg.mkdir(parents=True, exist_ok=True)
        count = 0

        def emit(rel: str, data: bytes) -> None:
            nonlocal count
            out = self.gfg / rel
            if not _is_within(self.gfg, out):
                return
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
            count += 1

        if tarfile.is_tarfile(archive):
            with tarfile.open(archive, "r:*") as tar:
                for m in tar:
                    if not m.isfile():
                        continue
                    name = "/" + m.name
                    i = name.find(needle)
                    if i == -1:
                        continue
                    fh = tar.extractfile(m)
                    if fh is not None:
                        emit(name[i + len(needle):], fh.read())
        elif zipfile.is_zipfile(archive):
            with zipfile.ZipFile(archive) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    name = "/" + info.filename
                    i = name.find(needle)
                    if i == -1:
                        continue
                    emit(name[i + len(needle):], zf.read(info))
        else:
            raise RuntimeError(f"Unrecognised archive format: {archive}")

        log.info("Extracted %d TransCoder function files to %s", count, self.gfg)
        if count == 0:
            raise RuntimeError(
                f"No files under '{subdir}' found in {archive}. "
                "Check dataset.transcoder_subdir / transcoder_url."
            )

    def iter_eligible(self, languages: list[str]) -> Iterator[ProblemSample]:
        yield from _iter_parallel_files(
            languages, self.LANG, base=self.gfg, kind="function", id_prefix=True
        )


# --------------------------------------------------------------------------- #
# HumanEval-X (THUDM/CodeGeeX)
# --------------------------------------------------------------------------- #
class HumanEvalXProvider(DatasetProvider):
    type = "humaneval_x"
    unit_kind = "function"

    # canonical -> (repo file token, extension). task_id prefix differs (e.g.
    # "CPP/0", "JavaScript/0") but problems correspond by their numeric suffix.
    LANG = {
        "Python": ("python", ".py"),
        "C++": ("cpp", ".cpp"),
        "Java": ("java", ".java"),
        "JavaScript": ("js", ".js"),
        "Go": ("go", ".go"),
    }

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.root = cfg.humaneval_x_root
        self.sources = self.root / "sources"     # sources/<token>/<num><ext>
        self.raw = self.root / "raw"

    def available_languages(self) -> list[str]:
        return list(self.LANG)

    def is_ready(self) -> bool:
        return self.sources.is_dir() and any(self.sources.iterdir())

    def ensure(self, offline: bool = False, force: bool = False) -> None:
        if self.is_ready() and not force:
            log.info("HumanEval-X data already present at %s", self.sources)
            return
        base = self.cfg.dataset.humaneval_x_base_url.rstrip("/")
        got_any = False
        for token, ext in self.LANG.values():
            url = f"{base}/{token}/data/humaneval_{token}.jsonl.gz"
            gz = self.raw / f"humaneval_{token}.jsonl.gz"
            try:
                # download_url returns the file to read (the local source for
                # file:// URLs, otherwise the downloaded ``gz``).
                got = download_url(url, gz, offline=offline, force=force)
            except FileNotFoundError:
                # A single missing language file must not abort the others
                # (network errors are different and are allowed to propagate).
                log.warning("HumanEval-X: %s not available, skipping", url)
                continue
            self._materialise(got, token, ext)
            got_any = True
        if not got_any:
            raise RuntimeError(
                f"No HumanEval-X language files found under {base}. "
                "Check dataset.humaneval_x_base_url."
            )

    def _materialise(self, gz: Path, token: str, ext: str) -> None:
        outdir = self.sources / token
        outdir.mkdir(parents=True, exist_ok=True)
        n = 0
        for rec in _read_jsonl_gz(gz):
            task_id = str(rec.get("task_id", ""))
            num = task_id.split("/")[-1]
            if not num:
                continue
            # The full reference solution is prompt (signature + docstring) + body.
            code = (rec.get("prompt", "") or "") + (rec.get("canonical_solution", "") or "")
            (outdir / f"{num}{ext}").write_text(code, encoding="utf-8")
            n += 1
        log.info("Materialised %d HumanEval-X %s solutions", n, token)

    def iter_eligible(self, languages: list[str]) -> Iterator[ProblemSample]:
        yield from _iter_parallel_files(
            languages, self.LANG, base=self.sources, kind="function", id_prefix=True
        )


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #
def _iter_parallel_files(
    languages: list[str],
    lang_map: dict[str, tuple[str, str]],
    base: Path,
    kind: str,
    id_prefix: bool,
) -> Iterator[ProblemSample]:
    """Yield problems whose id (file stem) exists in every requested language dir."""
    dirs: dict[str, tuple[Path, str]] = {}
    for lang in languages:
        if lang not in lang_map:
            log.warning("Language %r not available in this dataset; no eligible problems", lang)
            return
        token, ext = lang_map[lang]
        dirs[lang] = (base / token, ext)

    id_sets = []
    for _lang, (d, ext) in dirs.items():
        id_sets.append({p.name[: -len(ext)] for p in d.glob(f"*{ext}")} if d.is_dir() else set())
    common = set.intersection(*id_sets) if id_sets else set()

    def sort_key(s: str):
        return (0, int(s)) if s.isdigit() else (1, s)

    for pid in sorted(common, key=sort_key):
        units = {
            lang: SourceUnit(
                language=lang,
                path=d / f"{pid}{ext}",
                ext=ext,
                kind=kind,
                unit_id=f"{lang}/{pid}" if id_prefix else pid,
            )
            for lang, (d, ext) in dirs.items()
        }
        yield ProblemSample(problem_id=pid, units=units)


def _read_jsonl_gz(path: Path) -> Iterator[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def get_provider(cfg: Config) -> DatasetProvider:
    providers = {
        "codenet": CodeNetProvider,
        "transcoder": TransCoderProvider,
        "humaneval_x": HumanEvalXProvider,
    }
    try:
        return providers[cfg.dataset.type](cfg)
    except KeyError:
        raise ValueError(f"Unknown dataset.type: {cfg.dataset.type!r}")

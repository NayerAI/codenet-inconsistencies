"""Tests for the TransCoder and HumanEval-X providers using synthetic data
laid out exactly like the real datasets (no network)."""

import gzip
import json
import tarfile
from pathlib import Path

from codenet_eval.config import Config
from codenet_eval.providers import (
    HumanEvalXProvider,
    TransCoderProvider,
    get_provider,
)


# --------------------------------------------------------------------------- #
# TransCoder
# --------------------------------------------------------------------------- #
def _make_transcoder_tarball(tmp_path: Path) -> Path:
    """Mimic CodeGen-main/data/transcoder_evaluation_gfg/{cpp,java,python}/*."""
    stage = tmp_path / "CodeGen-main" / "data" / "transcoder_evaluation_gfg"
    files = {
        "cpp/FOO.cpp": "int FOO(){return 1;}",
        "java/FOO.java": "class FOO{}",
        "python/FOO.py": "def FOO():\n    return 1\n",
        # BAR is missing in python -> not eligible for the full triple.
        "cpp/BAR.cpp": "int BAR(){return 2;}",
        "java/BAR.java": "class BAR{}",
    }
    for rel, body in files.items():
        p = stage / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    archive = tmp_path / "codegen.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(tmp_path / "CodeGen-main", arcname="CodeGen-main")
    return archive


def test_transcoder_extract_and_eligibility(tmp_path):
    archive = _make_transcoder_tarball(tmp_path)
    cfg = Config.from_dict(
        {
            "data_dir": str(tmp_path / "data"),
            "dataset": {"type": "transcoder", "transcoder_url": f"file://{archive}"},
            "languages": ["C++", "Java", "Python"],
        }
    )
    provider = get_provider(cfg)
    assert isinstance(provider, TransCoderProvider)

    provider.ensure()
    assert provider.is_ready()

    samples = list(provider.iter_eligible(["C++", "Java", "Python"]))
    ids = {s.problem_id for s in samples}
    assert ids == {"FOO"}  # BAR excluded (no Python impl)

    foo = samples[0]
    assert set(foo.units) == {"C++", "Java", "Python"}
    assert foo.units["C++"].kind == "function"
    assert foo.units["Python"].path.is_file()
    assert foo.units["Python"].ext == ".py"

    # A pair that includes Python still finds BAR only in cpp+java.
    cj = {s.problem_id for s in provider.iter_eligible(["C++", "Java"])}
    assert cj == {"FOO", "BAR"}


# --------------------------------------------------------------------------- #
# HumanEval-X
# --------------------------------------------------------------------------- #
def _write_jsonl_gz(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


def _make_humaneval_base(tmp_path: Path) -> Path:
    """Mimic .../humaneval-x/<token>/data/humaneval_<token>.jsonl.gz."""
    base = tmp_path / "humaneval-x"
    langs = {
        "python": (".py", "Python"),
        "cpp": (".cpp", "CPP"),
    }
    for token, (_ext, prefix) in langs.items():
        recs = [
            {"task_id": f"{prefix}/0", "prompt": f"# {token} prompt 0\n", "canonical_solution": "sol0\n"},
            {"task_id": f"{prefix}/1", "prompt": f"# {token} prompt 1\n", "canonical_solution": "sol1\n"},
        ]
        _write_jsonl_gz(base / token / "data" / f"humaneval_{token}.jsonl.gz", recs)
    return base


def test_humaneval_x_materialise_and_eligibility(tmp_path):
    base = _make_humaneval_base(tmp_path)
    cfg = Config.from_dict(
        {
            "data_dir": str(tmp_path / "data"),
            "dataset": {"type": "humaneval_x", "humaneval_x_base_url": f"file://{base}"},
            "languages": ["Python", "C++"],
        }
    )
    provider = get_provider(cfg)
    assert isinstance(provider, HumanEvalXProvider)

    provider.ensure()
    assert provider.is_ready()

    samples = list(provider.iter_eligible(["Python", "C++"]))
    assert {s.problem_id for s in samples} == {"0", "1"}

    s0 = next(s for s in samples if s.problem_id == "0")
    # Full solution = prompt + canonical_solution.
    assert s0.units["Python"].path.read_text() == "# python prompt 0\nsol0\n"
    assert s0.units["C++"].ext == ".cpp"
    assert s0.units["Python"].unit_id == "Python/0"

    # A language not present in the dataset yields nothing.
    assert list(provider.iter_eligible(["Python", "Go"])) == []


def test_unknown_language_gives_no_eligible(tmp_path):
    base = _make_humaneval_base(tmp_path)
    cfg = Config.from_dict(
        {
            "data_dir": str(tmp_path / "data"),
            "dataset": {"type": "humaneval_x", "humaneval_x_base_url": f"file://{base}"},
            "languages": ["Python", "Rust"],   # Rust unsupported here
        }
    )
    provider = get_provider(cfg)
    provider.ensure()
    assert list(provider.iter_eligible(["Python", "Rust"])) == []

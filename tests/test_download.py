import tarfile
from pathlib import Path

import pytest

from codenet_eval.config import Config
from codenet_eval.download import extract_archive, is_extracted
from conftest import build_mini_codenet


def _make_tarball(tmp_path: Path) -> Config:
    # Build a Project_CodeNet tree, tar it up, and point a Config at it.
    staging = tmp_path / "staging"
    build_mini_codenet(staging / "Project_CodeNet")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    archive = data_dir / "Project_CodeNet.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(staging / "Project_CodeNet", arcname="Project_CodeNet")
    return Config.from_dict({"data_dir": str(data_dir)})


def test_extract_archive(tmp_path):
    cfg = _make_tarball(tmp_path)
    assert not is_extracted(cfg)
    root = extract_archive(cfg)
    assert is_extracted(cfg)
    assert (root / "metadata" / "p00001.csv").is_file()
    assert (root / "data" / "p00001" / "C" / "s0001.c").is_file()


def test_extract_is_idempotent(tmp_path):
    cfg = _make_tarball(tmp_path)
    extract_archive(cfg)
    # Second call is a no-op and must not raise.
    extract_archive(cfg)
    assert is_extracted(cfg)


def test_extract_missing_archive_raises(tmp_path):
    cfg = Config.from_dict({"data_dir": str(tmp_path / "empty")})
    with pytest.raises(FileNotFoundError):
        extract_archive(cfg)

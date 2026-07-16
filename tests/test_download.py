import tarfile
from pathlib import Path

import pytest

from codenet_eval.config import Config
from codenet_eval.download import ensure_dataset, extract_archive, is_extracted, local_archive_path
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


def test_local_archive_path_detection():
    assert local_archive_path("https://example.com/x.tar.gz") is None
    assert local_archive_path("http://example.com/x.tar.gz") is None
    assert str(local_archive_path("file:///abs/x.tar.gz")) == "/abs/x.tar.gz"
    assert str(local_archive_path("/abs/local/x.tar.gz")) == "/abs/local/x.tar.gz"
    assert str(local_archive_path("relative/x.tar.gz")) == "relative/x.tar.gz"


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


def test_offline_uses_existing_archive(tmp_path):
    # Archive already sitting in data_dir -> ensure_dataset must not hit network.
    cfg = _make_tarball(tmp_path)
    root = ensure_dataset(cfg, offline=True)
    assert is_extracted(cfg)
    assert (root / "metadata" / "p00001.csv").is_file()


def test_offline_without_archive_raises(tmp_path):
    cfg = Config.from_dict({"data_dir": str(tmp_path / "nope")})
    with pytest.raises(FileNotFoundError):
        ensure_dataset(cfg, offline=True)


def test_local_file_url_is_used_directly(tmp_path):
    # Build a tarball OUTSIDE data_dir and reference it via a file:// URL.
    cfg = _make_tarball(tmp_path)
    external = tmp_path / "external" / "codenet.tar.gz"
    external.parent.mkdir()
    (tmp_path / "data" / "Project_CodeNet.tar.gz").rename(external)

    target = tmp_path / "target"
    cfg2 = Config.from_dict(
        {"data_dir": str(target), "dataset": {"url": f"file://{external}"}}
    )
    root = ensure_dataset(cfg2)
    assert is_extracted(cfg2)
    assert (root / "metadata" / "p00001.csv").is_file()
    # The external source file must be left untouched (not moved into data_dir).
    assert external.is_file()
    assert not (target / "Project_CodeNet.tar.gz").exists()

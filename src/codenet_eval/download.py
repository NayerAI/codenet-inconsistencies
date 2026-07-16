"""Download and extract (a subset of) IBM Project CodeNet.

The IBM Data Asset eXchange serves CodeNet as a small number of ``.tar.gz``
archives.  We download the archive configured in ``dataset.url`` with resume
support and extract it into ``data_dir``.  Because the archive can be very
large, downloads are streamed and resumable, and re-running ``download`` is a
no-op once the dataset is present.
"""

from __future__ import annotations

import os
import tarfile
from pathlib import Path

import requests

from .config import Config
from .utils import get_logger, human_bytes, sha256_file

log = get_logger(__name__)

_CHUNK = 1 << 20  # 1 MiB


def is_extracted(cfg: Config) -> bool:
    """A dataset is considered present if its ``metadata`` directory exists."""
    return (cfg.dataset_root / "metadata").is_dir()


def download_archive(cfg: Config, force: bool = False) -> Path:
    """Download the dataset archive with HTTP-range resume support."""
    dest = cfg.archive_path
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists() and not force:
        existing = dest.stat().st_size
    else:
        if force and dest.exists():
            dest.unlink()
        existing = 0

    headers: dict[str, str] = {}
    mode = "wb"
    if existing:
        headers["Range"] = f"bytes={existing}-"
        mode = "ab"
        log.info("Resuming download at %s", human_bytes(existing))

    with requests.get(cfg.dataset.url, stream=True, headers=headers, timeout=60) as resp:
        if resp.status_code == 416:  # requested range not satisfiable -> already complete
            log.info("Archive already fully downloaded: %s", dest)
            return dest
        if existing and resp.status_code == 200:
            # Server ignored the Range header; restart from scratch.
            log.warning("Server does not support resume; restarting download")
            existing = 0
            mode = "wb"
        resp.raise_for_status()

        total = resp.headers.get("Content-Length")
        total_bytes = int(total) + existing if total is not None else None
        downloaded = existing
        next_report = existing
        with open(dest, mode) as handle:
            for chunk in resp.iter_content(chunk_size=_CHUNK):
                if not chunk:
                    continue
                handle.write(chunk)
                downloaded += len(chunk)
                if downloaded - next_report >= 100 * _CHUNK:
                    next_report = downloaded
                    if total_bytes:
                        pct = 100.0 * downloaded / total_bytes
                        log.info(
                            "Downloaded %s / %s (%.1f%%)",
                            human_bytes(downloaded),
                            human_bytes(total_bytes),
                            pct,
                        )
                    else:
                        log.info("Downloaded %s", human_bytes(downloaded))

    log.info("Download complete: %s (%s)", dest, human_bytes(dest.stat().st_size))

    if cfg.dataset.checksum_sha256:
        log.info("Verifying SHA-256 checksum ...")
        digest = sha256_file(dest)
        if digest.lower() != cfg.dataset.checksum_sha256.lower():
            raise ValueError(
                f"Checksum mismatch for {dest}: expected "
                f"{cfg.dataset.checksum_sha256}, got {digest}"
            )
        log.info("Checksum OK")

    return dest


def _is_within(directory: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def extract_archive(cfg: Config, force: bool = False) -> Path:
    """Extract the archive into ``data_dir`` (guarding against path traversal)."""
    if is_extracted(cfg) and not force:
        log.info("Dataset already extracted at %s", cfg.dataset_root)
        return cfg.dataset_root

    archive = cfg.archive_path
    if not archive.exists():
        raise FileNotFoundError(f"Archive not found: {archive}. Run 'download' first.")

    target = cfg.data_path
    log.info("Extracting %s -> %s (this may take a while)", archive, target)
    with tarfile.open(archive, "r:*") as tar:
        members = tar.getmembers()
        for member in members:
            member_path = target / member.name
            if not _is_within(target, member_path):
                raise RuntimeError(f"Refusing to extract outside target: {member.name}")
        tar.extractall(target)
    log.info("Extraction complete: %s", cfg.dataset_root)
    return cfg.dataset_root


def ensure_dataset(cfg: Config, force: bool = False, keep_archive: bool = True) -> Path:
    """Full download+extract flow, skipping any step that is already done."""
    if is_extracted(cfg) and not force:
        log.info("Dataset present at %s (skipping download)", cfg.dataset_root)
        return cfg.dataset_root
    download_archive(cfg, force=force)
    root = extract_archive(cfg, force=force)
    if not keep_archive:
        try:
            cfg.archive_path.unlink()
            log.info("Removed archive %s to save space", cfg.archive_path)
        except OSError:  # pragma: no cover
            pass
    return root

"""Command-line entry point.

Subcommands::

    codenet-eval download   # download + extract CodeNet into data/
    codenet-eval extract    # extract an already-downloaded archive (offline)
    codenet-eval inspect    # diagnose languages present + eligibility
    codenet-eval sample     # pick X% of eligible problems -> manifest.jsonl
    codenet-eval run        # query the LLM per language pair -> results.jsonl
    codenet-eval report     # summarise a run
    codenet-eval all        # download + sample + run + report

All commands accept ``--config path/to/config.yaml``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

import requests

from .config import Config
from .download import ensure_dataset, extract_archive
from .llm import LLMError, OpenRouterClient
from .report import format_summary, summarise, write_summary
from .runner import Runner, default_run_name
from .utils import get_logger, setup_logging

log = get_logger("codenet_eval.cli")


def _network_hint(cfg: Config, exc: Exception) -> None:
    """Explain a failed download and how to work around no-internet hosts."""
    log.error("Could not download %s: %s", cfg.dataset.url, exc)
    sys.stderr.write(
        "\nThe host could not reach the dataset URL (no internet / DNS, or a\n"
        "proxy is required -- common on HPC compute nodes). Options:\n"
        "  1. Behind a proxy? Set HTTPS_PROXY and forward it into the container:\n"
        "       apptainer run --env HTTPS_PROXY=$HTTPS_PROXY ... download\n"
        "  2. Download the tarball on a networked machine (login node), place it\n"
        f"       at {cfg.archive_path}, then run:  codenet-eval extract\n"
        "  3. Point dataset.url at the local file and run offline:\n"
        "       dataset: {url: file:///abs/path/Project_CodeNet.tar.gz}\n"
        "     or:  codenet-eval download --offline   (archive already in data/)\n\n"
    )


def _load_config(args: argparse.Namespace) -> Config:
    cfg = Config.load(args.config)
    if getattr(args, "data_dir", None):
        cfg.data_dir = args.data_dir
    if getattr(args, "log_level", None):
        cfg.log_level = args.log_level
    setup_logging(cfg.log_level)
    return cfg


def _resolve_run_dir(cfg: Config, run_name: Optional[str], create: bool) -> Path:
    if run_name:
        name = run_name
    elif cfg.output.run_name:
        name = cfg.output.run_name
    elif create:
        name = default_run_name()
    else:
        name = _latest_run_name(cfg)
        if name is None:
            raise SystemExit(
                "No run found. Provide --run-name or run 'sample' first."
            )
    run_dir = cfg.run_dir(name)
    if create:
        run_dir.mkdir(parents=True, exist_ok=True)
        cfg.dump_yaml(run_dir / "config.snapshot.yaml")
    return run_dir


def _latest_run_name(cfg: Config) -> Optional[str]:
    root = cfg.results_root
    if not root.is_dir():
        return None
    runs = [d for d in root.iterdir() if d.is_dir() and (d / "manifest.jsonl").is_file()]
    if not runs:
        return None
    latest = max(runs, key=lambda d: d.stat().st_mtime)
    return latest.name


# --- command handlers --------------------------------------------------------
def cmd_download(args: argparse.Namespace) -> int:
    cfg = _load_config(args)
    try:
        ensure_dataset(
            cfg,
            force=args.force,
            keep_archive=not args.no_keep_archive,
            offline=args.offline,
        )
    except requests.exceptions.RequestException as exc:
        _network_hint(cfg, exc)
        return 2
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    cfg = _load_config(args)
    extract_archive(cfg, force=args.force)
    print(f"Dataset extracted to {cfg.dataset_root}")
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    from collections import Counter

    from .dataset import CodeNetDataset

    cfg = _load_config(args)
    ds = CodeNetDataset(cfg)
    if not ds.exists():
        print(f"Dataset not found at {ds.root} (metadata/ missing).")
        return 1

    ids = ds.list_problem_ids()
    n = min(args.max_problems, len(ids))
    langs: Counter = Counter()
    have_accepted: Counter = Counter()
    have_file: Counter = Counter()
    eligible = 0
    for pid in ids[:n]:
        subs = ds.read_submissions(pid)
        accepted_langs, file_langs = set(), set()
        for s in subs:
            langs[s.language] += 1
            if s.accepted:
                accepted_langs.add(s.language)
                if s.language not in file_langs and s.path.is_file():
                    file_langs.add(s.language)
        for lang in cfg.languages:
            if lang in accepted_langs:
                have_accepted[lang] += 1
            if lang in file_langs:
                have_file[lang] += 1
        if ds.representatives(pid, cfg.languages, cfg.sampling.require_accepted):
            eligible += 1

    print(f"dataset_root       : {ds.root}")
    print(f"data/ exists       : {ds.data_dir.is_dir()}")
    print(f"problems (total)   : {len(ids)}")
    print(f"scanned            : {n}")
    print(f"languages present  : {dict(langs.most_common(20))}")
    print(f"configured langs   : {cfg.languages}")
    for lang in cfg.languages:
        print(
            f"  {lang:12s} accepted in {have_accepted[lang]:5d}/{n}"
            f"   source file resolves in {have_file[lang]:5d}/{n}"
        )
    print(f"eligible in scanned: {eligible}/{n}")
    if eligible == 0:
        print(
            "\nNo eligible problems in the scan. If 'source file resolves' is 0 "
            "but 'accepted in' is not, the on-disk layout differs from expected "
            "(check dataset_root/data/<problem>/<language>/<submission_id><.ext>)."
        )
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    from .demo import build_demo_dataset

    cfg = _load_config(args)
    build_demo_dataset(cfg)
    print(f"Synthetic demo dataset written under {cfg.dataset_root}")
    print("Next: codenet-eval --data-dir <dir> sample && ... run")
    return 0


def cmd_sample(args: argparse.Namespace) -> int:
    cfg = _load_config(args)
    runner = Runner(cfg)
    run_dir = _resolve_run_dir(cfg, args.run_name, create=True)
    runner.sample(run_dir)
    print(f"Manifest written to {run_dir / 'manifest.jsonl'}")
    return 0


def _make_client(cfg: Config) -> OpenRouterClient:
    try:
        return OpenRouterClient(cfg.llm)
    except LLMError as exc:
        raise SystemExit(str(exc))


def cmd_run(args: argparse.Namespace) -> int:
    cfg = _load_config(args)
    runner = Runner(cfg)
    # Reuse an explicit/latest run if there is one; otherwise start a fresh run.
    if args.run_name or cfg.output.run_name:
        run_dir = _resolve_run_dir(cfg, args.run_name, create=True)
    else:
        latest = _latest_run_name(cfg)
        run_dir = _resolve_run_dir(cfg, latest, create=latest is None)
    # 'run' is usable standalone: sample first if there is no manifest yet.
    if args.sample or not (run_dir / "manifest.jsonl").is_file():
        log.info("Sampling problems for run %s", run_dir.name)
        runner.sample(run_dir)
    client = None if args.dry_run else _make_client(cfg)
    runner.evaluate(run_dir, client, limit=args.limit, resume=not args.no_resume)
    if not args.dry_run:
        summary = summarise(run_dir)
        write_summary(run_dir, summary)
        print(format_summary(summary))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    cfg = _load_config(args)
    run_dir = _resolve_run_dir(cfg, args.run_name, create=False)
    summary = summarise(run_dir)
    write_summary(run_dir, summary)
    print(format_summary(summary))
    return 0


def cmd_all(args: argparse.Namespace) -> int:
    cfg = _load_config(args)
    try:
        ensure_dataset(
            cfg, force=False, keep_archive=not args.no_keep_archive, offline=args.offline
        )
    except requests.exceptions.RequestException as exc:
        _network_hint(cfg, exc)
        return 2
    runner = Runner(cfg)
    run_dir = _resolve_run_dir(cfg, args.run_name, create=True)
    runner.sample(run_dir)
    client = None if args.dry_run else _make_client(cfg)
    runner.evaluate(run_dir, client, limit=args.limit, resume=not args.no_resume)
    if not args.dry_run:
        summary = summarise(run_dir)
        write_summary(run_dir, summary)
        print(format_summary(summary))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codenet-eval",
        description="Find cross-language behavioural inconsistencies in CodeNet via an LLM.",
    )
    parser.add_argument("--config", "-c", default=None, help="Path to a YAML config file.")
    parser.add_argument("--data-dir", default=None, help="Override data_dir from the config.")
    parser.add_argument("--log-level", default=None, help="DEBUG, INFO, WARNING, ...")

    sub = parser.add_subparsers(dest="command", required=True)

    p_dl = sub.add_parser("download", help="Download and extract CodeNet.")
    p_dl.add_argument("--force", action="store_true", help="Re-download / re-extract.")
    p_dl.add_argument("--no-keep-archive", action="store_true", help="Delete the tarball after extraction.")
    p_dl.add_argument(
        "--offline", action="store_true",
        help="Do not access the network; extract an archive already in data/.",
    )
    p_dl.set_defaults(func=cmd_download)

    p_extract = sub.add_parser(
        "extract", help="Extract an already-downloaded archive (no network)."
    )
    p_extract.add_argument("--force", action="store_true", help="Re-extract even if present.")
    p_extract.set_defaults(func=cmd_extract)

    p_inspect = sub.add_parser(
        "inspect", help="Diagnose the dataset: languages present + eligibility."
    )
    p_inspect.add_argument("--max-problems", type=int, default=300, help="How many problems to scan.")
    p_inspect.set_defaults(func=cmd_inspect)

    p_demo = sub.add_parser(
        "demo", help="Write a tiny synthetic dataset for trying the pipeline offline."
    )
    p_demo.set_defaults(func=cmd_demo)

    p_sample = sub.add_parser("sample", help="Sample X%% of eligible problems.")
    p_sample.add_argument("--run-name", default=None)
    p_sample.set_defaults(func=cmd_sample)

    p_run = sub.add_parser("run", help="Query the LLM for each sampled language pair.")
    p_run.add_argument("--run-name", default=None)
    p_run.add_argument("--limit", type=int, default=None, help="Max LLM requests this invocation.")
    p_run.add_argument("--dry-run", action="store_true", help="Build prompts but do not call the API.")
    p_run.add_argument("--no-resume", action="store_true", help="Ignore existing results.jsonl.")
    p_run.add_argument("--sample", action="store_true", help="Force (re)sampling before running.")
    p_run.set_defaults(func=cmd_run)

    p_report = sub.add_parser("report", help="Summarise a completed run.")
    p_report.add_argument("--run-name", default=None)
    p_report.set_defaults(func=cmd_report)

    p_all = sub.add_parser("all", help="download + sample + run + report.")
    p_all.add_argument("--run-name", default=None)
    p_all.add_argument("--limit", type=int, default=None)
    p_all.add_argument("--dry-run", action="store_true")
    p_all.add_argument("--no-resume", action="store_true")
    p_all.add_argument("--no-keep-archive", action="store_true")
    p_all.add_argument(
        "--offline", action="store_true",
        help="Do not access the network; use an archive already in data/.",
    )
    p_all.set_defaults(func=cmd_all)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:  # pragma: no cover
        log.warning("Interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())

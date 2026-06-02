"""Command-line interface for the battery-usage pipeline.

Examples
--------
    python -m battery_usage download --n-users 25
    python -m battery_usage analyze
    python -m battery_usage all --n-users 40 --selection largest
"""
from __future__ import annotations

import argparse
import sys
from typing import Dict, Optional

from .config import load_config, Config


def _apply_overrides(args) -> Dict:
    cohort: Dict = {}
    if args.n_users is not None:
        cohort["n_users"] = args.n_users
    if args.seed is not None:
        cohort["seed"] = args.seed
    if args.selection is not None:
        cohort["selection"] = args.selection
    if args.min_bytes is not None:
        cohort["min_battery_bytes"] = args.min_bytes
    if args.min_rows is not None:
        cohort["min_rows"] = args.min_rows
    return {"cohort": cohort} if cohort else {}


def cmd_download(cfg: Config) -> None:
    from .s3_download import download_cohort
    print("[1/1] Downloading cohort from S3 ...")
    download_cohort(cfg)


def cmd_analyze(cfg: Config) -> None:
    from .aggregate import run_aggregation, build_cohort_table  # noqa: F401
    from .parse import iter_user_dirs, load_user
    from .visualize import plot_cohort, plot_top_users
    from .report import build_report

    print("[1/3] Building cohort feature table ...")
    res = run_aggregation(cfg)
    cohort, summary = res["cohort"], res["summary"]

    print("[2/3] Rendering figures ...")
    cohort_figs = plot_cohort(cohort, cfg)
    uds = [load_user(d) for d in iter_user_dirs(cfg.raw_dir)]
    user_figs = plot_top_users(uds, cfg, k=3)

    print("[3/3] Writing report ...")
    build_report(cfg, cohort, summary, cohort_figs, user_figs)
    print("Done. See", cfg.reports_dir / "report.md")


def build_parser() -> argparse.ArgumentParser:
    # Shared options live on the subparsers only, so they must FOLLOW the
    # subcommand (e.g. `download --n-users 20`). Attaching them to the top-level
    # parser too would let `--n-users 20 download` parse but be silently reset to
    # the None default by the subparser — a reproducibility trap — so we don't.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default=None, help="path to a config YAML (overrides defaults)")
    common.add_argument("--n-users", type=int, default=None, help="number of users in the cohort")
    common.add_argument("--seed", type=int, default=None, help="random seed for cohort selection")
    common.add_argument("--selection", choices=["random", "largest"], default=None,
                        help="cohort selection strategy")
    common.add_argument("--min-bytes", type=int, default=None, dest="min_bytes",
                        help="min latest-battery-file size to count a user as having real history")
    common.add_argument("--min-rows", type=int, default=None, dest="min_rows",
                        help="skip users whose parsed battery series has fewer than this many rows")

    p = argparse.ArgumentParser(prog="battery_usage", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("download", parents=[common], help="discover + download a cohort to data/raw/")
    sub.add_parser("analyze", parents=[common], help="parse downloaded data -> features, figures, report")
    sub.add_parser("all", parents=[common], help="download then analyze")
    return p


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config(args.config, overrides=_apply_overrides(args))
    if args.command == "download":
        cmd_download(cfg)
    elif args.command == "analyze":
        cmd_analyze(cfg)
    elif args.command == "all":
        cmd_download(cfg)
        cmd_analyze(cfg)
    else:  # pragma: no cover
        build_parser().print_help()
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

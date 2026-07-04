from __future__ import annotations

import argparse
from typing import List, Optional

from sentinel.cli import (
    backfill_cmds,
    backtest_cmds,
    inspect_cmds,
    intraday_cmds,
    scan_cmds,
    sync_cmds,
)
from sentinel.config import Settings
from sentinel.logging_utils import setup_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Taiwan stock strategy scanner")
    subparsers = parser.add_subparsers(dest="command", required=True)
    scan_cmds.register(subparsers)
    sync_cmds.register(subparsers)
    backtest_cmds.register(subparsers)
    intraday_cmds.register(subparsers)
    inspect_cmds.register(subparsers)
    backfill_cmds.register(subparsers)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    settings = Settings()
    setup_logging(settings.log_level)

    return args.handler(args, settings=settings, parser=parser)

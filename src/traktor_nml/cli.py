"""`traktor-nml` — the command line.

Dry run by default, one verb for the write, and one verb for a paragraph. The MCP server in `server.py` is the
same three calls with a different mouth.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config as config_module
from . import nml, sync


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="traktor-nml",
        description="Reconcile a Traktor collection against the files it is meant to hold.",
    )
    parser.add_argument("--config", type=Path, default=None,
                        help="the config.toml to read (default: the one beside this project)")
    parser.add_argument("--no-backup", action="store_true",
                        help="skip copying the collection first (not recommended)")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("plan", help="what it would do, writing nothing (the default)")
    commands.add_parser("status", help="where the collection and the lanes stand")
    commands.add_parser("apply", help="one backup, one write")
    pure = commands.add_parser(
        "purge", help="take out the entries whose file is gone (dry run unless --apply is given)")
    pure.add_argument("--apply", action="store_true", help="write it; without this nothing is removed")
    return parser


def _describe(found: sync.Plan) -> None:
    print(f"the collection at {found.where}")
    print(f"  {found.total} entries · {found.kept} whose file is there · "
          f"{len(found.repoints)} to repoint · {len(found.additions)} to add")
    for line in found.lines():
        print(f"  {line}")
    print()
    print(found.report())


def _plan(config: config_module.Config) -> int:
    _describe(sync.plan(config))
    print("nothing written yet: traktor-nml apply writes it")
    return 0


def _status(config: config_module.Config) -> int:
    print(sync.status(config))
    return 0


def _apply(config: config_module.Config, args: argparse.Namespace) -> int:
    found = sync.plan(config)
    if not found.writes():
        print(f"nothing to write: {found.report()}")
        print("the collection already holds every track in the lanes")
        return 0
    _describe(found)
    written = sync.write(found, backup=not args.no_backup)
    print(f"backed up to {written.name}" if written else "written with no backup — --no-backup was given")
    print("open Traktor and run Check Consistency → Analyze for the tracks it lists as unanalyzed")
    return 0


def _purge(config: config_module.Config, args: argparse.Namespace) -> int:
    """The entries whose file is gone, out — a dry run until `--apply` is given."""
    found, written = sync.purge(config, apply=args.apply, backup=not args.no_backup)
    if not found:
        print("nothing to purge: every entry points at a file that is there")
        return 0
    for removal in found:
        print(f"  {removal.line()}")
    print()
    if written is None:
        print(f"{len(found)} to remove — nothing has been written yet: "
              "traktor-nml purge --apply takes them out")
        return 0
    print(f"{len(found)} removed · backed up to {written.name}")
    print("the History files are untouched")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    config = config_module.load(args.config)
    try:
        if args.command == "status":
            return _status(config)
        if args.command == "purge":
            return _purge(config, args)
        if args.command == "apply":
            return _apply(config, args)
        return _plan(config)
    except (nml.CollectionMissing, nml.TraktorRunning, nml.Changed) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

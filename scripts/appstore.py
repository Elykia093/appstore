#!/usr/bin/env python3
"""One entry point for app store validation, synchronization and update checks."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# Support both `python scripts/appstore.py` and imports from tests, from any cwd.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import appstore_maintenance as maintenance
from scripts import appstore_updates as updates


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "validate", help="check metadata, versions and README offline without writing"
    )
    sync_parser = commands.add_parser(
        "sync", help="synchronize version directories and README"
    )
    sync_parser.add_argument(
        "--check", action="store_true", help="report drift without writing files"
    )
    sync_parser.add_argument(
        "--changed-in",
        help="only sync apps with compose changes in this commit (full SHA)",
    )
    sync_parser.add_argument(
        "--resolve-latest",
        action="store_true",
        help="resolve floating tags via GitHub releases (Renovate only)",
    )
    sync_parser.add_argument(
        "--github-output",
        type=Path,
        help="append app:old:new entries to the GitHub Actions output file",
    )
    updates_parser = commands.add_parser(
        "updates", help="check upstream releases and registry digests"
    )
    updates.configure_parser(updates_parser)
    args = parser.parse_args(argv)

    if args.command == "updates":
        updates.validate_args(updates_parser, args)
    elif args.command == "sync":
        if args.resolve_latest and not args.changed_in:
            sync_parser.error(
                "--resolve-latest requires --changed-in to scope the upstream lookup"
            )
        if args.github_output and (args.check or not args.changed_in):
            sync_parser.error(
                "--github-output requires --changed-in and cannot be used with --check"
            )

    try:
        if args.command == "validate":
            return maintenance.validate()
        if args.command == "sync":
            apps = (
                maintenance.changed_apps(args.changed_in) if args.changed_in else None
            )
            return maintenance.sync(
                apps,
                check=args.check,
                resolve_latest=args.resolve_latest,
                github_output=args.github_output,
            )
        return updates.run(args)
    except ModuleNotFoundError as exc:
        if exc.name != "yaml":
            raise
        print(
            "Validation requires PyYAML: python -m pip install PyYAML", file=sys.stderr
        )
        return 1
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"App store command failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

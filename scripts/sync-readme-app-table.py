#!/usr/bin/env python3
"""Synchronize README app versions and image tags from app compose files."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APPS_DIR = ROOT / "apps"
README = ROOT / "README.md"

APP_LABELS = {
    "anheyu": "Anheyu",
    "axonhub": "AxonHub",
    "cpa": "CPA / CLIProxyAPI",
    "lsky": "Lsky Pro",
    "lx-sync-server": "LX Sync Server",
    "metapi": "Metapi",
    "octopus": "Octopus",
}


def version_dir(app: str) -> Path:
    app_dir = APPS_DIR / app
    versions = sorted(
        path
        for path in app_dir.iterdir()
        if path.is_dir() and path.name != "__pycache__"
    )
    if len(versions) != 1:
        raise RuntimeError(f"{app} must have exactly one version directory, got {[p.name for p in versions]}")
    return versions[0]


def compose_image(compose_path: Path) -> str:
    for line in compose_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("image:") and "[ignore]" not in stripped:
            image = stripped.split("image:", 1)[1].strip().split()[0]
            return image.split("@", 1)[0]
    raise RuntimeError(f"{compose_path.relative_to(ROOT).as_posix()} does not contain an image line")


def current_rows() -> dict[str, tuple[str, str]]:
    rows: dict[str, tuple[str, str]] = {}
    for app in sorted(APP_LABELS):
        version = version_dir(app)
        image = compose_image(version / "docker-compose.yml")
        rows[APP_LABELS[app]] = (version.name, image)
    return rows


def update_readme(text: str) -> str:
    rows = current_rows()
    updated_lines: list[str] = []
    seen: set[str] = set()

    for line in text.splitlines(keepends=True):
        newline = "\n" if line.endswith("\n") else ""
        bare = line[:-1] if newline else line

        if bare.startswith("|") and bare.endswith("|"):
            cells = bare.split("|")
            if len(cells) >= 6:
                label = cells[1].strip()
                if label in rows:
                    version, image = rows[label]
                    cells[2] = f" `{version}` "
                    cells[3] = f" `{image}` "
                    bare = "|".join(cells)
                    seen.add(label)

        updated_lines.append(bare + newline)

    missing = sorted(set(rows) - seen)
    if missing:
        raise RuntimeError(f"README app table is missing rows: {missing}")

    return "".join(updated_lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if README.md is not synchronized")
    args = parser.parse_args()

    original = README.read_text(encoding="utf-8")
    updated = update_readme(original)

    if args.check:
        if updated != original:
            print("README.md app table is not synchronized", file=sys.stderr)
            return 1
        print("README.md app table is synchronized")
        return 0

    if updated != original:
        README.write_text(updated, encoding="utf-8")
        print("Updated README.md app table")
    else:
        print("README.md app table already synchronized")

    return 0


if __name__ == "__main__":
    sys.exit(main())

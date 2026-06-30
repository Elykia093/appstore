#!/usr/bin/env python3
"""Synchronize app version directories from compose image tags."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APPS_DIR = ROOT / "apps"
RESOLVER_PATH = ROOT / "scripts" / "resolve-app-version.py"
README_SYNC = ROOT / "scripts" / "sync-readme-app-table.py"


def load_resolver():
    spec = importlib.util.spec_from_file_location("app_version_resolver", RESOLVER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {RESOLVER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def version_dir(app_dir: Path) -> Path:
    versions = sorted(
        path
        for path in app_dir.iterdir()
        if path.is_dir() and path.name != "__pycache__"
    )
    if len(versions) != 1:
        raise RuntimeError(f"{app_dir.name} must have exactly one version directory, got {[p.name for p in versions]}")
    return versions[0]


def compose_image(compose_path: Path) -> str:
    for line in compose_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("image:") and "[ignore]" not in stripped:
            return stripped.split("image:", 1)[1].strip().split()[0]
    raise RuntimeError(f"{compose_path.relative_to(ROOT).as_posix()} does not contain an image line")


def resolve_version(resolver, app: str, image: str, current_version: str) -> str:
    tag = resolver.image_tag(image)
    if tag and tag != "latest":
        return resolver.normalize(tag)

    return current_version


def main() -> int:
    resolver = load_resolver()
    changed = False

    for app_dir in sorted(path for path in APPS_DIR.iterdir() if path.is_dir()):
        current_dir = version_dir(app_dir)
        image = compose_image(current_dir / "docker-compose.yml")
        target_version = resolve_version(resolver, app_dir.name, image, current_dir.name)

        if target_version == current_dir.name:
            continue

        target_dir = app_dir / target_version
        if target_dir.exists():
            raise RuntimeError(f"Target version directory already exists: {target_dir.relative_to(ROOT).as_posix()}")

        print(f"Renaming {current_dir.relative_to(ROOT).as_posix()} to {target_dir.relative_to(ROOT).as_posix()}")
        current_dir.rename(target_dir)
        changed = True

    subprocess.run([sys.executable, str(README_SYNC)], check=True)

    if changed:
        print("App version directories synchronized")
    else:
        print("App version directories already synchronized")
    return 0


if __name__ == "__main__":
    sys.exit(main())

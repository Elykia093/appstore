"""Shared metadata and file helpers for app store maintenance scripts."""

from __future__ import annotations

import json
import os
import shlex
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APPS_DIR = ROOT / "apps"

APP_DISPLAY_NAMES = {
    "anheyu": "Anheyu",
    "axonhub": "AxonHub",
    "cpa": "CLIProxyAPI",
    "lsky": "Lsky Pro",
    "new-api": "New API",
}


RELEASE_REPOS = {
    "anheyu": "anzhiyu-c/anheyu-app",
    "axonhub": "looplj/axonhub",
    "cpa": "router-for-me/CLIProxyAPI",
    "lsky": "lsky-org/lsky-pro",
    "new-api": "QuantumNous/new-api",
}


def normalize(tag: str) -> str:
    tag = tag.strip()
    return tag[1:] if tag.startswith("v") else tag


def image_tag(image: str) -> str:
    name_part = image.split("@", 1)[0].rsplit("/", 1)[-1]
    return name_part.rsplit(":", 1)[1] if ":" in name_part else ""


def latest_release_tag(repo: str) -> str:
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/releases/latest",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "appstore-version-resolver",
        },
    )
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    tag = payload.get("tag_name")
    if not isinstance(tag, str) or not tag:
        raise RuntimeError(f"Latest release for {repo} does not contain tag_name")
    return tag


def version_directories(app_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in app_dir.iterdir()
        if path.is_dir() and path.name != "__pycache__"
    )


def version_directory(app_dir: Path) -> Path:
    versions = version_directories(app_dir)
    if len(versions) != 1:
        raise RuntimeError(
            f"{app_dir.name} must have exactly one version directory, "
            f"got {[path.name for path in versions]}"
        )
    return versions[0]


def compose_image(compose_path: Path, *, strip_digest: bool = False) -> str:
    for line in compose_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.startswith("image:") or "[ignore]" in stripped:
            continue
        values = shlex.split(stripped.split("image:", 1)[1], comments=True)
        if len(values) != 1 or not values[0]:
            raise RuntimeError(
                f"{compose_path.as_posix()} must contain a non-empty image reference"
            )
        image = values[0]
        return image.split("@", 1)[0] if strip_digest else image

    raise RuntimeError(f"{compose_path.as_posix()} does not contain an image line")

#!/usr/bin/env python3
"""Resolve the 1Panel app version for a Renovate-updated Docker image."""

from __future__ import annotations

import json
import os
import sys
import urllib.request


RELEASE_REPOS = {
    "anheyu": "anzhiyu-c/anheyu-app",
    "axonhub": "looplj/axonhub",
    "cpa": "router-for-me/CLIProxyAPI",
    "lsky": "lsky-org/lsky-pro",
    "lx-sync-server": "XCQ0607/lxserver",
    "metapi": "cita-777/metapi",
    "octopus": "bestruirui/octopus",
}


def normalize(tag: str) -> str:
    tag = tag.strip()
    return tag[1:] if tag.startswith("v") else tag


def image_tag(image: str) -> str:
    image_without_digest = image.split("@", 1)[0]
    name_part = image_without_digest.rsplit("/", 1)[-1]
    if ":" not in name_part:
        return ""
    return name_part.rsplit(":", 1)[1]


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


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: resolve-app-version.py <app-name> <image>", file=sys.stderr)
        return 2

    app_name = sys.argv[1]
    image = sys.argv[2]
    tag = image_tag(image)

    if tag and tag != "latest":
        print(normalize(tag))
        return 0

    repo = RELEASE_REPOS.get(app_name)
    if not repo:
        print(f"No release source configured for {app_name}", file=sys.stderr)
        return 1

    print(normalize(latest_release_tag(repo)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

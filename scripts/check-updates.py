#!/usr/bin/env python3
"""Check whether curated apps match upstream releases and registry digests."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
APPS_DIR = ROOT / "apps"
RESOLVER_PATH = ROOT / "scripts" / "resolve-app-version.py"
IMAGE_RE = re.compile(r"^\s*image:\s*([^ #]+)", re.MULTILINE)
MANIFEST_ACCEPT = ", ".join(
    [
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ]
)


@dataclass
class ImageRef:
    display: str
    registry: str
    repo: str
    tag: str
    pinned_digest: str


@dataclass
class UpdateStatus:
    app: str
    current_version: str
    latest_version: str
    image: str
    pinned_digest: str
    remote_digest: str
    ok: bool
    error: str = ""


def load_resolver() -> Any:
    spec = importlib.util.spec_from_file_location("app_version_resolver", RESOLVER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {RESOLVER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def open_with_retry(request: urllib.request.Request) -> Any:
    last_error: BaseException | None = None
    for attempt in range(1, 4):
        try:
            return urllib.request.urlopen(request, timeout=30)
        except urllib.error.HTTPError as exc:
            if exc.code < 500 and exc.code != 429:
                raise
            last_error = exc
        except (ConnectionResetError, TimeoutError, urllib.error.URLError) as exc:
            last_error = exc

        if attempt < 3:
            time.sleep(attempt)

    assert last_error is not None
    raise last_error


def request_json(url: str, headers: dict[str, str] | None = None) -> Any:
    request = urllib.request.Request(url, headers=headers or {})
    with open_with_retry(request) as response:
        return json.load(response)


def latest_release_version(resolver: Any, app: str) -> str:
    repo = resolver.RELEASE_REPOS.get(app)
    if not repo:
        raise RuntimeError(f"No release source configured for {app}")

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "appstore-update-checker",
    }
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    payload = request_json(f"https://api.github.com/repos/{repo}/releases/latest", headers=headers)
    tag = payload.get("tag_name")
    if not isinstance(tag, str) or not tag:
        raise RuntimeError(f"Latest release for {repo} does not contain tag_name")
    return resolver.normalize(tag)


def version_dir(app_dir: Path) -> Path:
    versions = sorted(path for path in app_dir.iterdir() if path.is_dir() and path.name != "__pycache__")
    if len(versions) != 1:
        raise RuntimeError(f"{app_dir.name} must have exactly one version directory, got {[p.name for p in versions]}")
    return versions[0]


def compose_image(compose_path: Path) -> str:
    match = IMAGE_RE.search(compose_path.read_text(encoding="utf-8"))
    if not match:
        raise RuntimeError(f"{compose_path.relative_to(ROOT).as_posix()} does not contain an image line")
    return match.group(1)


def parse_image(image: str) -> ImageRef:
    if "@sha256:" not in image:
        raise RuntimeError(f"image is not digest pinned: {image}")

    ref, digest = image.split("@sha256:", 1)
    name_part = ref.rsplit("/", 1)[-1]
    if ":" not in name_part:
        raise RuntimeError(f"image does not contain an explicit tag: {image}")

    name, tag = ref.rsplit(":", 1)
    parts = name.split("/", 1)
    first = parts[0]

    if "." in first or ":" in first or first == "localhost":
        registry = first
        repo = parts[1] if len(parts) == 2 else ""
    else:
        registry = "docker.io"
        repo = name

    if registry == "docker.io":
        registry = "registry-1.docker.io"
        if "/" not in repo:
            repo = f"library/{repo}"

    if not repo:
        raise RuntimeError(f"image repository is empty: {image}")

    return ImageRef(
        display=ref,
        registry=registry,
        repo=repo,
        tag=tag,
        pinned_digest=f"sha256:{digest.strip()}",
    )


def registry_token(registry: str, repo: str) -> str:
    if registry == "registry-1.docker.io":
        params = urllib.parse.urlencode({"service": "registry.docker.io", "scope": f"repository:{repo}:pull"})
        payload = request_json(f"https://auth.docker.io/token?{params}")
        return str(payload.get("token") or "")

    if registry == "ghcr.io":
        params = urllib.parse.urlencode({"service": "ghcr.io", "scope": f"repository:{repo}:pull"})
        payload = request_json(f"https://ghcr.io/token?{params}")
        return str(payload.get("token") or "")

    return ""


def remote_manifest_digest(image: ImageRef) -> str:
    url = f"https://{image.registry}/v2/{image.repo}/manifests/{image.tag}"
    headers = {
        "Accept": MANIFEST_ACCEPT,
        "User-Agent": "appstore-update-checker",
    }
    token = registry_token(image.registry, image.repo)
    if token:
        headers["Authorization"] = f"Bearer {token}"

    for method in ("HEAD", "GET"):
        request = urllib.request.Request(url, headers=headers, method=method)
        try:
            with open_with_retry(request) as response:
                digest = response.headers.get("Docker-Content-Digest")
                if digest:
                    return digest
        except urllib.error.HTTPError as exc:
            if method == "HEAD" and exc.code in {401, 403, 404, 405}:
                continue
            raise

    raise RuntimeError(f"Registry did not return Docker-Content-Digest for {image.display}")


def check_app(resolver: Any, app_dir: Path) -> UpdateStatus:
    app = app_dir.name
    current_dir = version_dir(app_dir)
    image_text = compose_image(current_dir / "docker-compose.yml")
    image = parse_image(image_text)

    latest_version = latest_release_version(resolver, app)
    remote_digest = remote_manifest_digest(image)
    ok = current_dir.name == latest_version and image.pinned_digest == remote_digest

    return UpdateStatus(
        app=app,
        current_version=current_dir.name,
        latest_version=latest_version,
        image=image.display,
        pinned_digest=image.pinned_digest,
        remote_digest=remote_digest,
        ok=ok,
    )


def render_markdown(statuses: list[UpdateStatus]) -> str:
    lines = [
        "| App | Current | Latest | Image | Digest | Status |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for status in statuses:
        if status.error:
            state = f"ERROR: {status.error}"
            digest_state = "unknown"
        else:
            digest_state = "match" if status.pinned_digest == status.remote_digest else "stale"
            state = "ok" if status.ok else "stale"
        lines.append(
            "| {app} | `{current}` | `{latest}` | `{image}` | {digest} | {state} |".format(
                app=status.app,
                current=status.current_version,
                latest=status.latest_version or "unknown",
                image=status.image or "unknown",
                digest=digest_state,
                state=state,
            )
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    parser.add_argument("--no-fail", action="store_true", help="exit 0 even when stale apps are found")
    args = parser.parse_args()

    resolver = load_resolver()
    statuses: list[UpdateStatus] = []

    for app_dir in sorted(path for path in APPS_DIR.iterdir() if path.is_dir()):
        try:
            statuses.append(check_app(resolver, app_dir))
        except Exception as exc:
            statuses.append(
                UpdateStatus(
                    app=app_dir.name,
                    current_version="",
                    latest_version="",
                    image="",
                    pinned_digest="",
                    remote_digest="",
                    ok=False,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )

    if args.json:
        print(json.dumps([status.__dict__ for status in statuses], ensure_ascii=False, indent=2))
    else:
        print(render_markdown(statuses))

    failed = [status for status in statuses if not status.ok]
    if failed and not args.no_fail:
        print(f"\nUpdate check failed: {len(failed)} app(s) are stale or could not be checked.", file=sys.stderr)
        return 1

    if failed:
        print(f"\nUpdate check completed: {len(failed)} app(s) are stale or could not be checked.")
    else:
        print(f"\nUpdate check passed: {len(statuses)} app(s) are current.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

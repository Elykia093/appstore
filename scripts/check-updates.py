#!/usr/bin/env python3
"""Check whether curated apps match upstream releases and registry digests."""

from __future__ import annotations

import argparse
import http.client
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
APPS_DIR = ROOT / "apps"
RESOLVER_PATH = ROOT / "scripts" / "resolve-app-version.py"
IMAGE_RE = re.compile(r"^\s*image:\s*([^ #]+)", re.MULTILINE)
COMMIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
MANIFEST_ACCEPT = ", ".join(
    [
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ]
)
APP_DISPLAY_NAMES = {
    "anheyu": "Anheyu",
    "axonhub": "AxonHub",
    "cpa": "CLIProxyAPI",
    "lsky": "Lsky Pro",
    "new-api": "New API",
}


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


@dataclass
class MergedUpdate:
    app: str
    old_version: str
    new_version: str
    old_image: str
    new_image: str


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

    payload = request_json(
        f"https://api.github.com/repos/{repo}/releases/latest", headers=headers
    )
    tag = payload.get("tag_name")
    if not isinstance(tag, str) or not tag:
        raise RuntimeError(f"Latest release for {repo} does not contain tag_name")
    return resolver.normalize(tag)


def version_dir(app_dir: Path) -> Path:
    versions = sorted(
        path
        for path in app_dir.iterdir()
        if path.is_dir() and path.name != "__pycache__"
    )
    if len(versions) != 1:
        raise RuntimeError(
            f"{app_dir.name} must have exactly one version directory, got {[p.name for p in versions]}"
        )
    return versions[0]


def compose_image(compose_path: Path) -> str:
    match = IMAGE_RE.search(compose_path.read_text(encoding="utf-8"))
    if not match:
        raise RuntimeError(
            f"{compose_path.relative_to(ROOT).as_posix()} does not contain an image line"
        )
    return match.group(1).strip()


def parse_image(image: str) -> ImageRef:
    image = image.strip()
    if "@sha256:" in image:
        ref, digest = image.split("@sha256:", 1)
    else:
        ref, digest = image, ""
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
        pinned_digest=f"sha256:{digest.strip()}" if digest else "",
    )


def registry_token(registry: str, repo: str) -> str:
    if registry == "registry-1.docker.io":
        params = urllib.parse.urlencode(
            {"service": "registry.docker.io", "scope": f"repository:{repo}:pull"}
        )
        payload = request_json(f"https://auth.docker.io/token?{params}")
        return str(payload.get("token") or "")

    if registry == "ghcr.io":
        params = urllib.parse.urlencode(
            {"service": "ghcr.io", "scope": f"repository:{repo}:pull"}
        )
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

    raise RuntimeError(
        f"Registry did not return Docker-Content-Digest for {image.display}"
    )


def check_app(resolver: Any, app_dir: Path) -> UpdateStatus:
    app = app_dir.name
    current_dir = version_dir(app_dir)
    image_text = compose_image(current_dir / "docker-compose.yml")
    image = parse_image(image_text)

    latest_version = latest_release_version(resolver, app)
    remote_digest = remote_manifest_digest(image) if image.pinned_digest else ""
    ok = current_dir.name == latest_version and (
        not image.pinned_digest or image.pinned_digest == remote_digest
    )

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
            if not status.pinned_digest:
                digest_state = "unpinned"
            else:
                digest_state = (
                    "match" if status.pinned_digest == status.remote_digest else "stale"
                )
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


def changed_statuses(statuses: list[UpdateStatus]) -> list[UpdateStatus]:
    return [status for status in statuses if not status.error and not status.ok]


def error_statuses(statuses: list[UpdateStatus]) -> list[UpdateStatus]:
    return [status for status in statuses if status.error]


def telegram_credentials(environment: Mapping[str, str]) -> tuple[str, str]:
    token = environment.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = environment.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        raise RuntimeError(
            "Telegram notification requires both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID"
        )
    return token, chat_id


def validate_commit_sha(value: str, option_name: str) -> str:
    if not COMMIT_SHA_RE.fullmatch(value):
        raise ValueError(f"{option_name} must be a full 40-character commit SHA")
    return value.lower()


def git_output(args: list[str], *, allow_missing: bool = False) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    if result.returncode != 0:
        if allow_missing:
            return ""
        detail = result.stderr.strip() or "unknown git error"
        raise RuntimeError(f"git {' '.join(args[:2])} failed: {detail}")
    return result.stdout.strip()


def app_version_at(commit: str, app: str) -> str:
    output = git_output(
        ["ls-tree", "-d", "--name-only", f"{commit}:apps/{app}"],
        allow_missing=True,
    )
    versions = [line for line in output.splitlines() if line and line != "__pycache__"]
    if len(versions) > 1:
        raise RuntimeError(f"apps/{app} has multiple version directories at {commit}")
    return versions[0] if versions else ""


def app_image_at(commit: str, app: str, version: str) -> str:
    if not version:
        return ""
    compose = git_output(["show", f"{commit}:apps/{app}/{version}/docker-compose.yml"])
    match = IMAGE_RE.search(compose)
    if not match:
        raise RuntimeError(
            f"apps/{app}/{version}/docker-compose.yml does not contain an image line"
        )
    return match.group(1).strip()


def collect_merged_updates(before_sha: str, after_sha: str) -> list[MergedUpdate]:
    before_sha = validate_commit_sha(before_sha, "--before-sha")
    after_sha = validate_commit_sha(after_sha, "--after-sha")
    changed_files = git_output(
        ["diff", "--name-only", before_sha, after_sha, "--", "apps"]
    )
    apps = sorted(
        {
            match.group(1)
            for path in changed_files.splitlines()
            if (match := re.match(r"^apps/([^/]+)/", path))
        }
    )

    updates: list[MergedUpdate] = []
    for app in apps:
        old_version = app_version_at(before_sha, app)
        new_version = app_version_at(after_sha, app)
        old_image = app_image_at(before_sha, app, old_version)
        new_image = app_image_at(after_sha, app, new_version)
        if old_version == new_version and old_image == new_image:
            continue
        updates.append(
            MergedUpdate(
                app=app,
                old_version=old_version,
                new_version=new_version,
                old_image=old_image,
                new_image=new_image,
            )
        )
    return updates


def render_telegram_message(
    statuses: list[UpdateStatus],
    repository: str = "",
    run_id: str = "",
) -> str:
    updates = changed_statuses(statuses)
    errors = error_statuses(statuses)
    lines = ["1Panel 应用更新检查", ""]

    if updates:
        lines.extend(["待更新", ""])
        for status in updates:
            name = APP_DISPLAY_NAMES.get(status.app, status.app)
            lines.append(name)
            if status.current_version != status.latest_version:
                lines.append(
                    f"版本: {status.current_version} -> {status.latest_version}"
                )
            if status.pinned_digest and status.pinned_digest != status.remote_digest:
                lines.append("镜像摘要: 已变化")
            lines.append(f"当前镜像: {status.image}")
            lines.append("")

    if errors:
        lines.extend(["检查失败", ""])
        for status in errors:
            name = APP_DISPLAY_NAMES.get(status.app, status.app)
            lines.extend([name, status.error, ""])

    if repository and run_id:
        lines.append(f"检查详情: https://github.com/{repository}/actions/runs/{run_id}")
    return "\n".join(lines).rstrip()


def render_merged_message(
    updates: list[MergedUpdate],
    repository: str = "",
    after_sha: str = "",
    run_id: str = "",
) -> str:
    lines = ["1Panel 应用更新完成", ""]
    for update in updates:
        name = APP_DISPLAY_NAMES.get(update.app, update.app)
        lines.append(name)
        if (
            update.old_version
            and update.new_version
            and update.old_version != update.new_version
        ):
            lines.append(f"版本: {update.old_version} -> {update.new_version}")
        elif not update.old_version:
            lines.append(f"版本: 新增 {update.new_version}")
        elif not update.new_version:
            lines.append(f"版本: 移除 {update.old_version}")
        elif update.old_image != update.new_image:
            lines.append("镜像摘要: 已更新")
        lines.append("")

    if repository and after_sha:
        lines.append(f"提交: https://github.com/{repository}/commit/{after_sha}")
    if repository and run_id:
        lines.append(f"通知详情: https://github.com/{repository}/actions/runs/{run_id}")
    return "\n".join(lines).rstrip()


def send_telegram_message(
    token: str,
    chat_id: str,
    message: str,
) -> None:
    body: dict[str, Any] = {
        "chat_id": chat_id,
        "text": message,
        "link_preview_options": {"is_disabled": True},
    }

    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "appstore-update-checker",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"Telegram API request failed with HTTP {exc.code}"
        ) from None
    except (TimeoutError, urllib.error.URLError) as exc:
        raise RuntimeError(
            f"Telegram API request failed: {type(exc).__name__}"
        ) from None
    except http.client.InvalidURL:
        raise RuntimeError("Telegram API request could not be sent") from None
    except json.JSONDecodeError:
        raise RuntimeError("Telegram API returned invalid JSON") from None

    if not isinstance(result, dict) or result.get("ok") is not True:
        raise RuntimeError("Telegram API rejected the notification")


def notify_telegram(
    statuses: list[UpdateStatus],
    env: Mapping[str, str] | None = None,
) -> bool:
    environment = os.environ if env is None else env
    token, chat_id = telegram_credentials(environment)
    updates = changed_statuses(statuses)
    errors = error_statuses(statuses)
    if not updates and not errors:
        print("Telegram notification skipped: no stale apps or check errors.")
        return False

    message = render_telegram_message(
        statuses,
        repository=environment.get("GITHUB_REPOSITORY", ""),
        run_id=environment.get("GITHUB_RUN_ID", ""),
    )
    send_telegram_message(
        token,
        chat_id,
        message,
    )
    print(
        f"Telegram notification sent for {len(updates)} stale app(s) and {len(errors)} error(s)."
    )
    return True


def notify_merged_updates(
    before_sha: str,
    after_sha: str,
    env: Mapping[str, str] | None = None,
) -> bool:
    environment = os.environ if env is None else env
    token, chat_id = telegram_credentials(environment)
    updates = collect_merged_updates(before_sha, after_sha)
    if not updates:
        print("Telegram merge notification skipped: no app version or image changes.")
        return False

    message = render_merged_message(
        updates,
        repository=environment.get("GITHUB_REPOSITORY", ""),
        after_sha=after_sha,
        run_id=environment.get("GITHUB_RUN_ID", ""),
    )
    send_telegram_message(token, chat_id, message)
    print(f"Telegram merge notification sent for {len(updates)} app(s).")
    return True


def send_telegram_test(env: Mapping[str, str] | None = None) -> None:
    environment = os.environ if env is None else env
    token, chat_id = telegram_credentials(environment)

    lines = ["1Panel 应用更新通知测试", "", "Telegram Bot 配置正常。"]
    repository = environment.get("GITHUB_REPOSITORY", "")
    run_id = environment.get("GITHUB_RUN_ID", "")
    if repository and run_id:
        lines.extend(
            ["", f"检查详情: https://github.com/{repository}/actions/runs/{run_id}"]
        )
    send_telegram_message(
        token,
        chat_id,
        "\n".join(lines),
    )
    print("Telegram test notification sent.")


def status_exit_code(statuses: list[UpdateStatus], allow_stale: bool) -> int:
    if error_statuses(statuses):
        return 1
    if changed_statuses(statuses) and not allow_stale:
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json", action="store_true", help="print machine-readable JSON"
    )
    parser.add_argument(
        "--allow-stale",
        "--no-fail",
        dest="allow_stale",
        action="store_true",
        help="exit 0 for stale apps; upstream check errors still fail",
    )
    parser.add_argument(
        "--notify-telegram",
        action="store_true",
        help="send a Telegram notification for stale apps and upstream check errors",
    )
    parser.add_argument(
        "--telegram-test",
        action="store_true",
        help="send a Telegram test notification regardless of app update status",
    )
    parser.add_argument(
        "--notify-merged",
        action="store_true",
        help="send a Telegram notification for app changes between two commits",
    )
    parser.add_argument(
        "--before-sha", default="", help="commit before an app update merge"
    )
    parser.add_argument(
        "--after-sha", default="", help="commit after an app update merge"
    )
    args = parser.parse_args()

    notification_modes = sum(
        (args.notify_telegram, args.telegram_test, args.notify_merged)
    )
    if args.json and notification_modes:
        parser.error("--json cannot be combined with Telegram notification options")
    if notification_modes > 1:
        parser.error("Telegram notification options are mutually exclusive")
    if args.notify_merged and (not args.before_sha or not args.after_sha):
        parser.error("--notify-merged requires --before-sha and --after-sha")
    if not args.notify_merged and (args.before_sha or args.after_sha):
        parser.error("--before-sha and --after-sha require --notify-merged")
    if args.telegram_test:
        send_telegram_test()
        return 0
    if args.notify_merged:
        notify_merged_updates(args.before_sha, args.after_sha)
        return 0

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
        print(
            json.dumps(
                [status.__dict__ for status in statuses], ensure_ascii=False, indent=2
            )
        )
    else:
        print(render_markdown(statuses))

    if args.notify_telegram:
        notify_telegram(statuses)

    stale = changed_statuses(statuses)
    errors = error_statuses(statuses)
    result = status_exit_code(statuses, args.allow_stale)
    if errors:
        print(
            f"\nUpdate check failed: {len(errors)} app(s) could not be checked; "
            f"{len(stale)} app(s) are stale.",
            file=sys.stderr,
        )
    elif stale:
        print(f"\nUpdate check completed: {len(stale)} app(s) are stale.")
    else:
        print(f"\nUpdate check passed: {len(statuses)} app(s) are current.")
    return result


if __name__ == "__main__":
    sys.exit(main())

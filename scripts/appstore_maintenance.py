"""Local validation and synchronization for the curated 1Panel app store."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any

from scripts import appstore_metadata as metadata
from scripts.appstore_metadata import (
    APP_DISPLAY_NAMES,
    APPS_DIR,
    ROOT,
    compose_image,
    image_tag,
    normalize as normalize_version,
    version_directories,
    version_directory,
)

README = ROOT / "README.md"
RENOVATE = ROOT / "renovate.json"
ROOT_DATA = ROOT / "data.yaml"

EXPECTED_APPS = set(APP_DISPLAY_NAMES)

FLOATING_IMAGE_TAG_APPS = {"lsky"}
ALLOWED_IMPLICIT_ENV = {"CONTAINER_NAME"}
COMPOSE_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?:(?::?[-+?]).*)?\}")


class Validator:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def require(self, condition: bool, message: str) -> None:
        if not condition:
            self.error(message)


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def load_yaml(path: Path, validator: Validator) -> Any:
    import yaml

    try:
        with path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except Exception as exc:  # pragma: no cover - surfaced in CI output
        validator.error(f"{rel(path)} is not valid YAML: {exc}")
        return None


def collect_env_keys(value: Any) -> set[str]:
    keys: set[str] = set()

    if isinstance(value, dict):
        env_key = value.get("envKey")
        if isinstance(env_key, str) and env_key:
            keys.add(env_key)
        for child in value.values():
            keys.update(collect_env_keys(child))
    elif isinstance(value, list):
        for item in value:
            keys.update(collect_env_keys(item))

    return keys


def collect_compose_vars(value: Any) -> set[str]:
    variables: set[str] = set()

    if isinstance(value, str):
        variables.update(COMPOSE_VAR_RE.findall(value))
    elif isinstance(value, dict):
        for child in value.values():
            variables.update(collect_compose_vars(child))
    elif isinstance(value, list):
        for item in value:
            variables.update(collect_compose_vars(item))

    return variables


def collect_images(compose: Any) -> list[str]:
    if not isinstance(compose, dict):
        return []

    services = compose.get("services")
    if not isinstance(services, dict):
        return []

    images: list[str] = []
    for service_name, service in services.items():
        if not isinstance(service, dict):
            continue
        image = service.get("image")
        if isinstance(image, str) and image:
            images.append(image)
        else:
            images.append(f"<missing image for service {service_name}>")
    return images


def image_base(image: str) -> str:
    return image.split("@", 1)[0]


def validate_all_yaml(validator: Validator) -> dict[Path, Any]:
    loaded: dict[Path, Any] = {}
    for path in sorted(ROOT.rglob("*.yml")) + sorted(ROOT.rglob("*.yaml")):
        loaded[path] = load_yaml(path, validator)
    return loaded


def validate_root(loaded: dict[Path, Any], validator: Validator) -> set[str]:
    root_data = loaded.get(ROOT_DATA)
    validator.require(ROOT_DATA.exists(), "data.yaml is missing")

    tags: set[str] = set()
    if isinstance(root_data, dict):
        props = root_data.get("additionalProperties", {})
        root_tag_list = props.get("tags", []) if isinstance(props, dict) else []
        for item in root_tag_list:
            if isinstance(item, dict) and isinstance(item.get("key"), str):
                tags.add(item["key"].lower())

    validator.require(bool(tags), "data.yaml does not define additionalProperties.tags")
    return tags


def validate_app_metadata(
    app: str,
    data_path: Path,
    data: Any,
    root_tags: set[str],
    validator: Validator,
) -> None:
    if not isinstance(data, dict):
        return

    properties = data.get("additionalProperties")
    validator.require(
        isinstance(properties, dict),
        f"{rel(data_path)} missing additionalProperties",
    )
    if not isinstance(properties, dict):
        return

    validator.require(
        properties.get("key") == app,
        f"{rel(data_path)} additionalProperties.key must be {app}",
    )
    tags = properties.get("tags", [])
    if not isinstance(tags, list):
        validator.error(f"{rel(data_path)} additionalProperties.tags must be a list")
        return

    missing_tags = [
        tag for tag in tags if isinstance(tag, str) and tag.lower() not in root_tags
    ]
    validator.require(
        not missing_tags,
        f"{rel(data_path)} uses tags missing from data.yaml: {missing_tags}",
    )


def validate_app_images(
    app: str,
    app_version: str,
    version_data_path: Path,
    compose_path: Path,
    version_data: Any,
    compose: Any,
    readme_text: str,
    validator: Validator,
) -> list[str]:
    missing_vars = sorted(
        collect_compose_vars(compose)
        - (collect_env_keys(version_data) | ALLOWED_IMPLICIT_ENV)
    )
    validator.require(
        not missing_vars,
        f"{rel(compose_path)} variables are not declared in "
        f"{rel(version_data_path)}: {missing_vars}",
    )

    images = collect_images(compose)
    validator.require(images, f"{rel(compose_path)} has no service images")
    for image in images:
        validator.require(
            "@sha256:" in image,
            f"{rel(compose_path)} image is not digest pinned: {image}",
        )
        validator.require(
            ":" in image_base(image),
            f"{rel(compose_path)} image must include an explicit tag: {image}",
        )

        tag = image_tag(image)
        if app in FLOATING_IMAGE_TAG_APPS:
            validator.require(
                tag == "latest",
                f"{rel(compose_path)} image tag must stay latest because the mirror "
                f"has no version tags: {image}",
            )
        else:
            validator.require(
                normalize_version(tag) == app_version,
                f"{rel(compose_path)} image tag must match version directory "
                f"{app_version}: {image}",
            )

        base = image_base(image)
        validator.require(
            base in readme_text,
            f"README.md does not mention compose image {base}",
        )
    return images


def validate_app(
    loaded: dict[Path, Any],
    root_tags: set[str],
    readme_text: str,
    app: str,
    validator: Validator,
) -> list[str]:
    app_dir = APPS_DIR / app
    root_data_path = app_dir / "data.yml"
    for required in (root_data_path, app_dir / "README.md", app_dir / "logo.png"):
        validator.require(required.exists(), f"{rel(required)} is missing")

    if not app_dir.is_dir():
        return []

    versions = version_directories(app_dir)
    version_names = [path.name for path in versions]
    validator.require(
        len(versions) == 1 and versions[0].name != "latest",
        f"{app} must have exactly one real version directory instead of latest, "
        f"got {version_names}",
    )
    if not versions:
        return []

    version = versions[0]
    version_data_path = version / "data.yml"
    compose_path = version / "docker-compose.yml"
    for required in (version_data_path, compose_path):
        validator.require(required.exists(), f"{rel(required)} is missing")

    validate_app_metadata(
        app,
        root_data_path,
        loaded.get(root_data_path),
        root_tags,
        validator,
    )
    images = validate_app_images(
        app,
        version.name,
        version_data_path,
        compose_path,
        loaded.get(version_data_path),
        loaded.get(compose_path),
        readme_text,
        validator,
    )
    validator.require(app in readme_text, f"README.md does not mention app id {app}")
    return images


def validate_apps(
    loaded: dict[Path, Any], root_tags: set[str], validator: Validator
) -> list[str]:
    if not APPS_DIR.is_dir():
        validator.error("apps directory is missing")
        return []

    app_dirs = {path.name for path in APPS_DIR.iterdir() if path.is_dir()}
    validator.require(
        app_dirs == EXPECTED_APPS,
        f"apps directory mismatch: expected {sorted(EXPECTED_APPS)}, got {sorted(app_dirs)}",
    )

    readme_text = README.read_text(encoding="utf-8") if README.exists() else ""
    validator.require(README.exists(), "README.md is missing")

    images: list[str] = []
    for app in sorted(EXPECTED_APPS):
        images.extend(validate_app(loaded, root_tags, readme_text, app, validator))
    return images


def validate_renovate(validator: Validator) -> None:
    validator.require(RENOVATE.exists(), "renovate.json is missing")
    if not RENOVATE.exists():
        return

    try:
        config = json.loads(RENOVATE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        validator.error(f"renovate.json is invalid JSON: {exc}")
        return

    validator.require(
        config.get("enabledManagers") == ["docker-compose"],
        "renovate.json enabledManagers must be exactly ['docker-compose']",
    )
    validator.require(
        config.get("includePaths") == ["apps/**/docker-compose.yml"],
        "renovate.json includePaths must be exactly ['apps/**/docker-compose.yml']",
    )

    package_rules = config.get("packageRules")
    validator.require(
        isinstance(package_rules, list) and bool(package_rules),
        "renovate.json packageRules is empty",
    )
    digest_rules = [
        (index, rule)
        for index, rule in enumerate(package_rules or [])
        if isinstance(rule, dict)
        and rule.get("matchManagers") == ["docker-compose"]
        and rule.get("matchDatasources") == ["docker"]
        and rule.get("pinDigests") is True
        and rule.get("versioning") == "docker"
    ]
    validator.require(
        bool(digest_rules),
        "renovate.json must pin docker-compose Docker image digests with docker versioning",
    )
    axonhub_version_rules = [
        (index, rule)
        for index, rule in enumerate(package_rules or [])
        if isinstance(rule, dict)
        and rule.get("matchManagers") == ["docker-compose"]
        and rule.get("matchDatasources") == ["docker"]
        and "looplj/axonhub" in rule.get("matchPackageNames", [])
        and rule.get("allowedVersions") == "!/-(?:amd64|arm64)$/"
        and rule.get("versioning") == "pep440"
        and rule.get("ignoreUnstable") is False
    ]
    validator.require(
        bool(axonhub_version_rules),
        "renovate.json must use pep440 versioning for looplj/axonhub, allow prerelease updates, and exclude architecture-specific tags",
    )
    new_api_version_rules = [
        (index, rule)
        for index, rule in enumerate(package_rules or [])
        if isinstance(rule, dict)
        and rule.get("matchManagers") == ["docker-compose"]
        and rule.get("matchDatasources") == ["docker"]
        and "calciumion/new-api" in rule.get("matchPackageNames", [])
        and rule.get("allowedVersions") == "!/-(?:amd64|arm64)$/"
        and rule.get("pinDigests") is True
        and rule.get("versioning") == "loose"
    ]
    validator.require(
        bool(new_api_version_rules),
        "renovate.json must pin calciumion/new-api digests with loose versioning and exclude architecture-specific tags",
    )
    if digest_rules and axonhub_version_rules:
        validator.require(
            axonhub_version_rules[-1][0] > digest_rules[-1][0],
            "renovate.json looplj/axonhub pep440 versioning rule must appear after the general Docker rule",
        )
    if digest_rules and new_api_version_rules:
        validator.require(
            new_api_version_rules[-1][0] > digest_rules[-1][0],
            "renovate.json calciumion/new-api loose versioning rule must appear after the general digest pin rule",
        )


def current_rows(
    planned_versions: dict[str, str] | None = None,
) -> dict[str, tuple[str, str]]:
    rows: dict[str, tuple[str, str]] = {}
    for app, label in sorted(APP_DISPLAY_NAMES.items()):
        version = version_directory(APPS_DIR / app)
        image = compose_image(version / "docker-compose.yml", strip_digest=True)
        rows[label] = ((planned_versions or {}).get(app, version.name), image)
    return rows


def update_readme(text: str, planned_versions: dict[str, str] | None = None) -> str:
    rows = current_rows(planned_versions)
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


def changed_apps(commit: str) -> list[str]:
    """Select only apps whose compose files changed in a Renovate commit."""
    if not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
        raise ValueError("--changed-in requires a full 40-character commit SHA")
    result = subprocess.run(
        [
            "git",
            "diff-tree",
            "--root",
            "--no-commit-id",
            "--name-only",
            "-r",
            "-z",
            commit,
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    apps = set()
    for filename in result.stdout.split("\0"):
        parts = PurePosixPath(filename).parts
        if len(parts) == 4 and parts[0] == "apps" and parts[3] == "docker-compose.yml":
            apps.add(parts[1])
    return sorted(apps)


def version_plan(
    apps: list[str] | None = None, *, resolve_latest: bool = False
) -> list[tuple[Path, Path]]:
    if apps is None:
        apps = sorted(path.name for path in APPS_DIR.iterdir() if path.is_dir())
    plans = []
    for app in sorted(set(apps)):
        if app not in APP_DISPLAY_NAMES:
            raise ValueError(f"Unknown app: {app}")
        app_dir = APPS_DIR / app
        current = version_directory(app_dir)
        tag = image_tag(compose_image(current / "docker-compose.yml"))
        if tag and tag != "latest":
            version = normalize_version(tag)
        elif resolve_latest:
            version = normalize_version(
                metadata.latest_release_tag(metadata.RELEASE_REPOS[app])
            )
        else:
            # Local validation/sync must not depend on GitHub or rename latest images.
            version = current.name
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", version):
            raise ValueError(f"Invalid version directory for {app}: {version!r}")
        target = app_dir / version
        if current != target and target.exists():
            raise RuntimeError(
                f"Target version directory already exists: {rel(target)}"
            )
        plans.append((current, target))
    return plans


def sync(
    apps: list[str] | None = None,
    *,
    check: bool = False,
    resolve_latest: bool = False,
    github_output: Path | None = None,
) -> int:
    # Resolve every destination and render README before changing any files.
    plans = version_plan(apps, resolve_latest=resolve_latest)
    original = README.read_text(encoding="utf-8")
    updated = update_readme(
        original, {source.parent.name: target.name for source, target in plans}
    )
    mismatches = [(source, target) for source, target in plans if source != target]
    if check:
        for source, target in mismatches:
            print(
                f"Version directory mismatch: {rel(source)} should be {rel(target)}",
                file=sys.stderr,
            )
        if updated != original:
            print("README.md app table is not synchronized", file=sys.stderr)
        if mismatches or updated != original:
            return 1
        print("App version directories and README app table are synchronized")
        return 0

    for source, target in mismatches:
        print(f"Renaming {rel(source)} to {rel(target)}")
        source.rename(target)
    if updated != original:
        README.write_text(updated, encoding="utf-8")
        print("Updated README.md app table")
    if github_output is not None:
        # Include digest-only changes too: the workflow commits every selected app.
        entries = [
            f"{source.parent.name}:{source.name}:{target.name}"
            for source, target in plans
        ]
        with github_output.open("a", encoding="utf-8") as output:
            output.write(f"apps={','.join(entries)}\n")
    print("App version directories and README app table synchronized")
    return 0


def validate() -> int:
    validator = Validator()

    loaded = validate_all_yaml(validator)
    root_tags = validate_root(loaded, validator)
    images = validate_apps(loaded, root_tags, validator)
    validate_renovate(validator)

    try:
        synchronized = sync(check=True) == 0
        validator.require(
            synchronized, "Version directories or README app table are not synchronized"
        )
    except (OSError, RuntimeError, ValueError) as exc:
        validator.error(str(exc))

    if validator.errors:
        print("App store validation failed:")
        for item in validator.errors:
            print(f"- {item}")
        return 1

    print(
        f"App store validation passed: {len(EXPECTED_APPS)} apps, {len(images)} image(s)."
    )
    return 0

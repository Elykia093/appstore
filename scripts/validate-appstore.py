#!/usr/bin/env python3
"""Validate the curated 1Panel app store layout."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
APPS_DIR = ROOT / "apps"
README = ROOT / "README.md"
RENOVATE = ROOT / "renovate.json"
ROOT_DATA = ROOT / "data.yaml"

EXPECTED_APPS = {
    "anheyu",
    "axonhub",
    "cpa",
    "lsky",
    "lx-sync-server",
    "metapi",
    "octopus",
}

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


def validate_apps(loaded: dict[Path, Any], root_tags: set[str], validator: Validator) -> list[str]:
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

    all_images: list[str] = []
    for app in sorted(EXPECTED_APPS):
        app_dir = APPS_DIR / app
        latest_dir = app_dir / "latest"
        root_data_path = app_dir / "data.yml"
        version_data_path = latest_dir / "data.yml"
        compose_path = latest_dir / "docker-compose.yml"

        for required in (root_data_path, app_dir / "README.md", app_dir / "logo.png"):
            validator.require(required.exists(), f"{rel(required)} is missing")

        if not app_dir.is_dir():
            continue

        version_dirs = sorted(
            path.name
            for path in app_dir.iterdir()
            if path.is_dir() and path.name != "__pycache__"
        )
        validator.require(
            version_dirs == ["latest"],
            f"{app} must have exactly one version directory named latest, got {version_dirs}",
        )

        for required in (version_data_path, compose_path):
            validator.require(required.exists(), f"{rel(required)} is missing")

        app_data = loaded.get(root_data_path)
        version_data = loaded.get(version_data_path)
        compose = loaded.get(compose_path)

        if isinstance(app_data, dict):
            props = app_data.get("additionalProperties")
            validator.require(isinstance(props, dict), f"{rel(root_data_path)} missing additionalProperties")
            if isinstance(props, dict):
                validator.require(
                    props.get("key") == app,
                    f"{rel(root_data_path)} additionalProperties.key must be {app}",
                )
                tags = props.get("tags", [])
                if isinstance(tags, list):
                    missing_tags = [
                        tag
                        for tag in tags
                        if isinstance(tag, str) and tag.lower() not in root_tags
                    ]
                    validator.require(
                        not missing_tags,
                        f"{rel(root_data_path)} uses tags missing from data.yaml: {missing_tags}",
                    )
                else:
                    validator.error(f"{rel(root_data_path)} additionalProperties.tags must be a list")

        form_env_keys = collect_env_keys(version_data) | ALLOWED_IMPLICIT_ENV
        compose_vars = collect_compose_vars(compose)
        missing_vars = sorted(compose_vars - form_env_keys)
        validator.require(
            not missing_vars,
            f"{rel(compose_path)} variables are not declared in {rel(version_data_path)}: {missing_vars}",
        )

        images = collect_images(compose)
        validator.require(images, f"{rel(compose_path)} has no service images")
        for image in images:
            all_images.append(image)
            validator.require(
                "@sha256:" in image,
                f"{rel(compose_path)} image is not digest pinned: {image}",
            )
            validator.require(
                ":" in image_base(image),
                f"{rel(compose_path)} image must include an explicit tag before digest: {image}",
            )

            base = image_base(image)
            validator.require(
                base in readme_text,
                f"README.md does not mention compose image {base}",
            )

        validator.require(
            app in readme_text,
            f"README.md does not mention app id {app}",
        )

    return all_images


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
    validator.require(isinstance(package_rules, list) and bool(package_rules), "renovate.json packageRules is empty")
    digest_rules = [
        rule
        for rule in package_rules or []
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


def main() -> int:
    validator = Validator()

    loaded = validate_all_yaml(validator)
    root_tags = validate_root(loaded, validator)
    images = validate_apps(loaded, root_tags, validator)
    validate_renovate(validator)

    if validator.errors:
        print("App store validation failed:")
        for item in validator.errors:
            print(f"- {item}")
        return 1

    print(f"App store validation passed: {len(EXPECTED_APPS)} apps, {len(images)} image(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

import contextlib
import io
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import appstore
from scripts import appstore_maintenance as validate_appstore
from scripts import appstore_metadata


ROOT = Path(__file__).resolve().parents[1]


class ValidateAppStoreTests(unittest.TestCase):
    def test_validate_app_metadata_reports_key_and_tag_mismatches(self):
        validator = validate_appstore.Validator()
        data_path = ROOT / "apps" / "cpa" / "data.yml"

        validate_appstore.validate_app_metadata(
            "cpa",
            data_path,
            {"additionalProperties": {"key": "wrong", "tags": ["unknown"]}},
            {"tool"},
            validator,
        )

        self.assertTrue(
            any(
                "additionalProperties.key must be cpa" in error
                for error in validator.errors
            )
        )
        self.assertTrue(
            any("tags missing from data.yaml" in error for error in validator.errors)
        )

    def test_validate_app_images_reports_template_drift(self):
        validator = validate_appstore.Validator()
        version_dir = ROOT / "apps" / "cpa" / "1.0.0"
        images = validate_appstore.validate_app_images(
            "cpa",
            "1.0.0",
            version_dir / "data.yml",
            version_dir / "docker-compose.yml",
            {"formFields": [{"envKey": "DECLARED"}]},
            {
                "services": {
                    "cpa": {
                        "image": "example/cpa:v2",
                        "environment": ["MISSING=${MISSING}"],
                    }
                }
            },
            "",
            validator,
        )

        self.assertEqual(images, ["example/cpa:v2"])
        for expected in (
            "variables are not declared",
            "image is not digest pinned",
            "image tag must match version directory 1.0.0",
            "README.md does not mention compose image",
        ):
            with self.subTest(expected=expected):
                self.assertTrue(any(expected in error for error in validator.errors))


class SynchronizationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.apps = self.root / "apps"
        self.readme = self.root / "README.md"
        self.labels = {"cpa": "CLIProxyAPI", "lsky": "Lsky Pro"}
        self.cpa = self.apps / "cpa" / "1.0"
        self.lsky = self.apps / "lsky" / "2.1"
        for folder, image in (
            (self.cpa, "example/cpa:v2.0@sha256:abc"),
            (self.lsky, "example/lsky:latest@sha256:def"),
        ):
            folder.mkdir(parents=True)
            (folder / "docker-compose.yml").write_text(
                f"services:\n  app:\n    image: {image}\n", encoding="utf-8"
            )
            (folder / "data.yml").write_text("formFields: []\n", encoding="utf-8")
        self.readme.write_text(
            "| CLIProxyAPI | `1.0` | `example/cpa:v2.0` | port | data |\n"
            "| Lsky Pro | `2.1` | `example/lsky:latest` | port | data |\n",
            encoding="utf-8",
        )
        patches = patch.multiple(
            validate_appstore,
            ROOT=self.root,
            APPS_DIR=self.apps,
            README=self.readme,
            APP_DISPLAY_NAMES=self.labels,
        )
        patches.start()
        self.addCleanup(patches.stop)
        self.output = io.StringIO()
        for redirect in (
            contextlib.redirect_stdout(self.output),
            contextlib.redirect_stderr(self.output),
        ):
            redirect.__enter__()
            self.addCleanup(redirect.__exit__, None, None, None)

    def snapshot(self):
        return {
            str(path.relative_to(self.root)): path.read_bytes()
            for path in self.root.rglob("*")
            if path.is_file()
        }

    def test_check_reports_drift_without_writes_or_network(self):
        before = self.snapshot()
        with patch.object(appstore_metadata, "latest_release_tag") as upstream:
            self.assertEqual(appstore.main(["sync", "--check"]), 1)
        upstream.assert_not_called()
        self.assertEqual(self.snapshot(), before)
        self.assertIn("1.0 should be apps/cpa/2.0", self.output.getvalue())

    def test_sync_renames_from_tag_updates_readme_and_is_idempotent(self):
        with patch.object(appstore_metadata, "latest_release_tag") as upstream:
            self.assertEqual(appstore.main(["sync"]), 0)
            after = self.snapshot()
            self.assertEqual(appstore.main(["sync", "--check"]), 0)
            self.assertEqual(appstore.main(["sync"]), 0)
        upstream.assert_not_called()
        self.assertFalse(self.cpa.exists())
        self.assertTrue((self.apps / "cpa" / "2.0" / "data.yml").is_file())
        self.assertTrue(self.lsky.is_dir())
        self.assertIn(
            "| CLIProxyAPI | `2.0` |", self.readme.read_text(encoding="utf-8")
        )
        self.assertEqual(after, self.snapshot())

    def test_upstream_sync_is_scoped_and_outputs_digest_only_changes(self):
        output = self.root / "github-output"
        with patch.object(
            appstore_metadata, "latest_release_tag", return_value="v2.2"
        ) as upstream:
            validate_appstore.sync(["lsky"], resolve_latest=True, github_output=output)
        upstream.assert_called_once_with("lsky-org/lsky-pro")
        self.assertTrue(self.cpa.exists())
        self.assertTrue((self.apps / "lsky" / "2.2").is_dir())
        self.assertEqual(output.read_text(), "apps=lsky:2.1:2.2\n")
        validate_appstore.sync(["lsky"], github_output=output)
        self.assertIn("apps=lsky:2.2:2.2\n", output.read_text())

    def test_target_collision_prevents_all_writes(self):
        # The first app needs a rename, but the second app's target is occupied.
        (self.apps / "lsky" / "2.2").write_text("occupied", encoding="utf-8")
        before = self.snapshot()
        with patch.object(appstore_metadata, "latest_release_tag", return_value="v2.2"):
            with self.assertRaisesRegex(RuntimeError, "already exists"):
                validate_appstore.sync(resolve_latest=True)
        self.assertEqual(self.snapshot(), before)

    def test_invalid_upstream_version_cannot_escape_app_directory(self):
        before = self.snapshot()
        with patch.object(
            appstore_metadata, "latest_release_tag", return_value="../../escape"
        ):
            with self.assertRaisesRegex(ValueError, "Invalid version"):
                validate_appstore.sync(["lsky"], resolve_latest=True)
        self.assertEqual(self.snapshot(), before)

    def test_missing_readme_row_prevents_directory_moves(self):
        self.readme.write_text("No app table\n", encoding="utf-8")
        before = self.snapshot()
        self.assertEqual(appstore.main(["sync"]), 1)
        self.assertEqual(self.snapshot(), before)

    def test_changed_commit_selects_only_compose_apps_and_preserves_digest_updates(
        self,
    ):
        subprocess.run(
            ["git", "init", "-q", str(self.root)], check=True, capture_output=True
        )
        subprocess.run(
            ["git", "add", "."], cwd=self.root, check=True, capture_output=True
        )
        command = [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=/dev/null",
            "commit",
            "-qm",
        ]
        subprocess.run(
            command + ["initial"], cwd=self.root, check=True, capture_output=True
        )
        compose = self.lsky / "docker-compose.yml"
        compose.write_text(
            compose.read_text().replace("sha256:def", "sha256:new"), encoding="utf-8"
        )
        (self.cpa / "data.yml").write_text(
            "formFields: [] # changed\n", encoding="utf-8"
        )
        subprocess.run(
            ["git", "add", "."], cwd=self.root, check=True, capture_output=True
        )
        subprocess.run(
            command + ["digest update"], cwd=self.root, check=True, capture_output=True
        )
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=self.root, text=True
        ).strip()
        self.assertEqual(validate_appstore.changed_apps(sha), ["lsky"])
        output = self.root / "github-output"
        with patch.object(appstore_metadata, "latest_release_tag", return_value="v2.1"):
            self.assertEqual(
                appstore.main(
                    [
                        "sync",
                        "--changed-in",
                        sha,
                        "--resolve-latest",
                        "--github-output",
                        str(output),
                    ]
                ),
                0,
            )
        self.assertEqual(output.read_text(), "apps=lsky:2.1:2.1\n")
        self.assertTrue(self.cpa.exists())


class UnifiedEntryTests(unittest.TestCase):
    def test_help_works_from_outside_repository_without_site_packages(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, "-S", str(ROOT / "scripts" / "appstore.py"), "--help"],
                cwd=directory,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("{validate,sync,updates}", result.stdout)

    def test_validate_rejects_readme_drift_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "apps", root / "apps")
            for name in ("README.md", "data.yaml", "renovate.json"):
                shutil.copyfile(ROOT / name, root / name)
            readme = root / "README.md"
            text = readme.read_text(encoding="utf-8")
            version = appstore_metadata.version_directory(ROOT / "apps" / "cpa").name
            readme.write_text(
                text.replace(
                    f"| CLIProxyAPI | `{version}` |", "| CLIProxyAPI | `outdated` |"
                ),
                encoding="utf-8",
            )
            before = readme.read_bytes()
            with patch.multiple(
                validate_appstore,
                ROOT=root,
                APPS_DIR=root / "apps",
                README=readme,
                ROOT_DATA=root / "data.yaml",
                RENOVATE=root / "renovate.json",
            ):
                with (
                    contextlib.redirect_stdout(io.StringIO()),
                    contextlib.redirect_stderr(io.StringIO()),
                    patch.object(appstore_metadata, "latest_release_tag") as upstream,
                ):
                    self.assertEqual(appstore.main(["validate"]), 1)
            upstream.assert_not_called()
            self.assertEqual(readme.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()

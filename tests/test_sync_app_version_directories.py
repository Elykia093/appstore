import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "sync-app-version-directories.py"
SPEC = importlib.util.spec_from_file_location("sync_app_versions", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load {MODULE_PATH}")
sync_app_versions = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync_app_versions)


class Resolver:
    @staticmethod
    def image_tag(image: str) -> str:
        return image.rsplit(":", 1)[1]

    @staticmethod
    def normalize(version: str) -> str:
        return version.removeprefix("v")


class SyncAppVersionDirectoriesTests(unittest.TestCase):
    def test_find_mismatches_reports_version_directory_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            apps_dir = Path(directory) / "apps"
            compose = apps_dir / "cpa" / "7.2.100" / "docker-compose.yml"
            compose.parent.mkdir(parents=True)
            compose.write_text(
                "services:\n  app:\n    image: eceasy/cpa:v7.2.102\n", encoding="utf-8"
            )

            with patch.object(sync_app_versions, "APPS_DIR", apps_dir):
                mismatches = sync_app_versions.find_mismatches(Resolver())

        self.assertEqual(len(mismatches), 1)
        self.assertEqual(mismatches[0][0].name, "7.2.100")
        self.assertEqual(mismatches[0][1].name, "7.2.102")

    def test_check_mode_reports_mismatch_without_writing_or_syncing_readme(self):
        current = ROOT / "apps" / "cpa" / "7.2.100"
        target = ROOT / "apps" / "cpa" / "7.2.102"
        stderr = io.StringIO()
        with patch.object(sync_app_versions, "load_resolver", return_value=Resolver()):
            with patch.object(
                sync_app_versions, "find_mismatches", return_value=[(current, target)]
            ):
                with patch.object(sync_app_versions.subprocess, "run") as run:
                    with patch.object(
                        sys, "argv", ["sync-app-version-directories.py", "--check"]
                    ):
                        with contextlib.redirect_stderr(stderr):
                            result = sync_app_versions.main()

        self.assertEqual(result, 1)
        self.assertIn("7.2.100 should be apps/cpa/7.2.102", stderr.getvalue())
        run.assert_not_called()

    def test_check_mode_succeeds_when_directories_match(self):
        stdout = io.StringIO()
        with patch.object(sync_app_versions, "load_resolver", return_value=Resolver()):
            with patch.object(sync_app_versions, "find_mismatches", return_value=[]):
                with patch.object(sync_app_versions.subprocess, "run") as run:
                    with patch.object(
                        sys, "argv", ["sync-app-version-directories.py", "--check"]
                    ):
                        with contextlib.redirect_stdout(stdout):
                            result = sync_app_versions.main()

        self.assertEqual(result, 0)
        self.assertIn("are synchronized", stdout.getvalue())
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()

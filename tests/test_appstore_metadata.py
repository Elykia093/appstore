import tempfile
import unittest
from pathlib import Path


from scripts import appstore_metadata


class AppStoreMetadataTests(unittest.TestCase):
    def test_compose_image_accepts_quotes_and_reports_empty_values(self):
        with tempfile.TemporaryDirectory() as directory:
            compose = Path(directory) / "docker-compose.yml"
            compose.write_text(
                'image: "example/app:v2@sha256:abc" # pinned\n', encoding="utf-8"
            )
            self.assertEqual(
                appstore_metadata.compose_image(compose), "example/app:v2@sha256:abc"
            )
            for empty in ("image: # empty\n", 'image: ""\n'):
                compose.write_text(empty, encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "non-empty image"):
                    appstore_metadata.compose_image(compose)

    def test_compose_image_ignores_marked_images_and_can_strip_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            compose = Path(directory) / "docker-compose.yml"
            compose.write_text(
                "services:\n"
                "  ignored:\n"
                "    image: example/ignored:v1 # [ignore]\n"
                "  app:\n"
                "    image: example/app:v2@sha256:abc\n",
                encoding="utf-8",
            )

            self.assertEqual(
                appstore_metadata.compose_image(compose), "example/app:v2@sha256:abc"
            )
            self.assertEqual(
                appstore_metadata.compose_image(compose, strip_digest=True),
                "example/app:v2",
            )

    def test_version_directory_ignores_python_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            app_dir = Path(directory) / "cpa"
            version = app_dir / "7.2.124"
            version.mkdir(parents=True)
            (app_dir / "__pycache__").mkdir()

            self.assertEqual(appstore_metadata.version_directory(app_dir), version)

    def test_version_directory_requires_exactly_one_version(self):
        with tempfile.TemporaryDirectory() as directory:
            app_dir = Path(directory) / "cpa"
            (app_dir / "7.2.123").mkdir(parents=True)
            (app_dir / "7.2.124").mkdir()

            with self.assertRaisesRegex(RuntimeError, "exactly one version"):
                appstore_metadata.version_directory(app_dir)


if __name__ == "__main__":
    unittest.main()

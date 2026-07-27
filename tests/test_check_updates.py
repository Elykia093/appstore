import contextlib
import importlib.util
import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "check-updates.py"
SPEC = importlib.util.spec_from_file_location("check_updates", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load {MODULE_PATH}")
check_updates = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = check_updates
SPEC.loader.exec_module(check_updates)


class TelegramNotificationTests(unittest.TestCase):
    def status(
        self,
        app: str,
        current: str,
        latest: str,
        pinned: str = "",
        remote: str = "",
    ):
        return check_updates.UpdateStatus(
            app=app,
            current_version=current,
            latest_version=latest,
            image=f"example/{app}:v{current}",
            pinned_digest=pinned,
            remote_digest=remote,
            ok=current == latest and (not pinned or pinned == remote),
        )

    @staticmethod
    def env() -> dict[str, str]:
        return {
            "TELEGRAM_BOT_TOKEN": "test-token",
            "TELEGRAM_CHAT_ID": "-100123",
            "GITHUB_REPOSITORY": "owner/repo",
            "GITHUB_RUN_ID": "123",
        }

    def test_daily_message_contains_stale_and_error_sections(self):
        statuses = [
            self.status("cpa", "7.2.77", "7.2.77"),
            self.status("axonhub", "1.0.0-beta5", "1.0.0-beta6"),
            self.status(
                "new-api", "1.0.0-rc.21", "1.0.0-rc.21", "sha256:old", "sha256:new"
            ),
            check_updates.UpdateStatus(
                "lsky", "", "", "", "", "", False, "TimeoutError: upstream"
            ),
        ]

        message = check_updates.render_telegram_message(statuses, "owner/repo", "123")

        self.assertIn("待更新", message)
        self.assertIn("AxonHub", message)
        self.assertIn("1.0.0-beta5 -> 1.0.0-beta6", message)
        self.assertIn("镜像摘要: 已变化", message)
        self.assertIn("检查失败", message)
        self.assertIn("Lsky Pro", message)
        self.assertIn("TimeoutError: upstream", message)
        self.assertNotIn("CLIProxyAPI", message)
        self.assertIn("https://github.com/owner/repo/actions/runs/123", message)

    def test_notify_requires_both_secrets_even_when_all_apps_are_current(self):
        with self.assertRaisesRegex(RuntimeError, "both TELEGRAM_BOT_TOKEN"):
            check_updates.notify_telegram([self.status("cpa", "7.2.77", "7.2.77")], {})

    def test_notify_rejects_partial_secret_configuration(self):
        with self.assertRaisesRegex(RuntimeError, "both TELEGRAM_BOT_TOKEN"):
            check_updates.notify_telegram(
                [self.status("cpa", "7.2.77", "7.2.77")],
                {"TELEGRAM_BOT_TOKEN": "test-token"},
            )

    def test_notify_skips_when_no_app_is_stale_and_no_check_failed(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            sent = check_updates.notify_telegram(
                [self.status("cpa", "7.2.77", "7.2.77")],
                self.env(),
            )

        self.assertFalse(sent)
        self.assertIn("no stale apps or check errors", output.getvalue())

    def test_notify_sends_same_stale_update_on_every_daily_run(self):
        responses = [io.BytesIO(b'{"ok": true}'), io.BytesIO(b'{"ok": true}')]
        with patch.object(
            check_updates.urllib.request, "urlopen", side_effect=responses
        ) as urlopen:
            first = check_updates.notify_telegram(
                [self.status("cpa", "7.2.76", "7.2.77")],
                self.env(),
            )
            second = check_updates.notify_telegram(
                [self.status("cpa", "7.2.76", "7.2.77")],
                self.env(),
            )

        self.assertTrue(first)
        self.assertTrue(second)
        self.assertEqual(urlopen.call_count, 2)

    def test_notify_sends_check_errors(self):
        response = io.BytesIO(b'{"ok": true}')
        error = check_updates.UpdateStatus(
            "cpa", "", "", "", "", "", False, "TimeoutError: upstream"
        )
        with patch.object(
            check_updates.urllib.request, "urlopen", return_value=response
        ) as urlopen:
            sent = check_updates.notify_telegram([error], self.env())

        self.assertTrue(sent)
        payload = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertIn("检查失败", payload["text"])
        self.assertIn("TimeoutError: upstream", payload["text"])

    def test_notify_sends_json_payload_without_exposing_token(self):
        response = io.BytesIO(b'{"ok": true}')
        output = io.StringIO()
        with patch.object(
            check_updates.urllib.request, "urlopen", return_value=response
        ) as urlopen:
            with contextlib.redirect_stdout(output):
                sent = check_updates.notify_telegram(
                    [self.status("cpa", "7.2.76", "7.2.77")],
                    self.env(),
                )

        self.assertTrue(sent)
        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(set(payload), {"chat_id", "text", "link_preview_options"})
        self.assertEqual(payload["chat_id"], "-100123")
        self.assertIn("7.2.76 -> 7.2.77", payload["text"])
        self.assertNotIn("test-token", output.getvalue())

    def test_merged_message_reports_version_and_digest_changes(self):
        updates = [
            check_updates.MergedUpdate(
                "cpa",
                "7.2.100",
                "7.2.102",
                "eceasy/cpa:v7.2.100",
                "eceasy/cpa:v7.2.102",
            ),
            check_updates.MergedUpdate(
                "lx-sync-server",
                "2.0.0",
                "2.0.0",
                "image@sha256:old",
                "image@sha256:new",
            ),
        ]

        message = check_updates.render_merged_message(
            updates,
            repository="owner/repo",
            after_sha="a" * 40,
            run_id="123",
        )

        self.assertIn("1Panel 应用更新完成", message)
        self.assertIn("7.2.100 -> 7.2.102", message)
        self.assertIn("镜像摘要: 已更新", message)
        self.assertIn(f"https://github.com/owner/repo/commit/{'a' * 40}", message)

    def test_collect_merged_updates_uses_changed_apps_and_commit_snapshots(self):
        with patch.object(
            check_updates,
            "git_output",
            return_value="apps/cpa/7.2.102/docker-compose.yml\nREADME.md",
        ):
            with patch.object(
                check_updates,
                "app_version_at",
                side_effect=["7.2.100", "7.2.102"],
            ):
                with patch.object(
                    check_updates,
                    "app_image_at",
                    side_effect=["eceasy/cpa:v7.2.100", "eceasy/cpa:v7.2.102"],
                ):
                    updates = check_updates.collect_merged_updates("a" * 40, "b" * 40)

        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].app, "cpa")
        self.assertEqual(updates[0].old_version, "7.2.100")
        self.assertEqual(updates[0].new_version, "7.2.102")

    def test_collect_merged_updates_rejects_abbreviated_sha(self):
        with self.assertRaisesRegex(ValueError, "40-character"):
            check_updates.collect_merged_updates("abc123", "b" * 40)

    def test_app_image_snapshot_failure_is_not_suppressed(self):
        with patch.object(
            check_updates, "git_output", side_effect=RuntimeError("git show failed")
        ):
            with self.assertRaisesRegex(RuntimeError, "git show failed"):
                check_updates.app_image_at("a" * 40, "cpa", "7.2.102")

    def test_notify_merged_sends_expected_payload(self):
        response = io.BytesIO(b'{"ok": true}')
        update = check_updates.MergedUpdate(
            "new-api", "0.9.1", "0.9.2", "image:v0.9.1", "image:v0.9.2"
        )
        with patch.object(
            check_updates, "collect_merged_updates", return_value=[update]
        ):
            with patch.object(
                check_updates.urllib.request, "urlopen", return_value=response
            ) as urlopen:
                sent = check_updates.notify_merged_updates(
                    "a" * 40, "b" * 40, self.env()
                )

        self.assertTrue(sent)
        payload = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertIn("New API", payload["text"])
        self.assertIn("0.9.1 -> 0.9.2", payload["text"])

    def test_status_exit_code_allows_stale_but_never_check_errors(self):
        stale = [self.status("cpa", "7.2.76", "7.2.77")]
        error = [
            check_updates.UpdateStatus("cpa", "", "", "", "", "", False, "timeout")
        ]

        self.assertEqual(check_updates.status_exit_code(stale, allow_stale=True), 0)
        self.assertEqual(check_updates.status_exit_code(stale, allow_stale=False), 1)
        self.assertEqual(check_updates.status_exit_code(error, allow_stale=True), 1)

    def test_telegram_test_notification_sends_expected_payload(self):
        response = io.BytesIO(b'{"ok": true}')
        with patch.object(
            check_updates.urllib.request, "urlopen", return_value=response
        ) as urlopen:
            check_updates.send_telegram_test(self.env())

        payload = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertIn("配置正常", payload["text"])

    def test_http_error_does_not_expose_bot_token(self):
        error = urllib.error.HTTPError(
            "https://api.telegram.org/bottest-token/sendMessage",
            400,
            "Bad Request",
            {},
            io.BytesIO(b'{"ok": false}'),
        )
        self.addCleanup(error.close)
        with patch.object(check_updates.urllib.request, "urlopen", side_effect=error):
            with self.assertRaisesRegex(RuntimeError, "HTTP 400") as raised:
                check_updates.send_telegram_message("test-token", "-100123", "message")

        self.assertNotIn("test-token", str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)

    def test_failed_notification_propagates_failure(self):
        error = urllib.error.HTTPError(
            "https://api.telegram.org/bottest-token/sendMessage",
            500,
            "Internal Server Error",
            {},
            io.BytesIO(b'{"ok": false}'),
        )
        self.addCleanup(error.close)
        with patch.object(check_updates.urllib.request, "urlopen", side_effect=error):
            with self.assertRaisesRegex(RuntimeError, "HTTP 500"):
                check_updates.notify_telegram(
                    [self.status("cpa", "7.2.75", "7.2.77")],
                    self.env(),
                )

    def test_invalid_bot_token_does_not_expose_token_in_error(self):
        token = "test-token\ninvalid"
        with self.assertRaises(RuntimeError) as raised:
            check_updates.send_telegram_message(token, "-100123", "message")

        self.assertNotIn(token, str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)

    def test_telegram_test_main_bypasses_update_checks(self):
        with patch.object(check_updates, "load_resolver") as load_resolver:
            with patch.object(check_updates, "send_telegram_test") as send_test:
                with patch.object(sys, "argv", ["check-updates.py", "--telegram-test"]):
                    result = check_updates.main()

        self.assertEqual(result, 0)
        send_test.assert_called_once_with()
        load_resolver.assert_not_called()

    def test_notify_merged_main_bypasses_update_checks(self):
        with patch.object(check_updates, "load_resolver") as load_resolver:
            with patch.object(check_updates, "notify_merged_updates") as notify:
                with patch.object(
                    sys,
                    "argv",
                    [
                        "check-updates.py",
                        "--notify-merged",
                        "--before-sha",
                        "a" * 40,
                        "--after-sha",
                        "b" * 40,
                    ],
                ):
                    result = check_updates.main()

        self.assertEqual(result, 0)
        notify.assert_called_once_with("a" * 40, "b" * 40)
        load_resolver.assert_not_called()


if __name__ == "__main__":
    unittest.main()

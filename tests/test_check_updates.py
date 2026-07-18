import contextlib
import importlib.util
import io
import json
import sys
import tempfile
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
    def status(self, app: str, current: str, latest: str, pinned: str = "", remote: str = ""):
        return check_updates.UpdateStatus(
            app=app,
            current_version=current,
            latest_version=latest,
            image=f"example/{app}:v{current}",
            pinned_digest=pinned,
            remote_digest=remote,
            ok=current == latest and (not pinned or pinned == remote),
        )

    def test_message_contains_version_and_digest_updates_only(self):
        statuses = [
            self.status("cpa", "7.2.77", "7.2.77"),
            self.status("axonhub", "1.0.0-beta5", "1.0.0-beta6"),
            self.status("new-api", "1.0.0-rc.21", "1.0.0-rc.21", "sha256:old", "sha256:new"),
            check_updates.UpdateStatus("lsky", "", "", "", "", "", False, "TimeoutError: upstream"),
        ]

        message = check_updates.render_telegram_message(statuses, "owner/repo", "123")

        self.assertIn("AxonHub", message)
        self.assertIn("1.0.0-beta5 -> 1.0.0-beta6", message)
        self.assertIn("New API", message)
        self.assertIn("镜像摘要: 已变化", message)
        self.assertIn("当前镜像: example/axonhub:v1.0.0-beta5", message)
        self.assertNotIn("CLIProxyAPI", message)
        self.assertNotIn("Lsky Pro", message)
        self.assertIn("https://github.com/owner/repo/actions/runs/123", message)

    def test_notify_skips_when_no_app_is_stale(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            sent = check_updates.notify_telegram([self.status("cpa", "7.2.77", "7.2.77")], {})

        self.assertFalse(sent)
        self.assertIn("no app updates", output.getvalue())

    def test_notify_rejects_partial_secret_configuration(self):
        with self.assertRaisesRegex(RuntimeError, "both TELEGRAM_BOT_TOKEN"):
            check_updates.notify_telegram(
                [self.status("cpa", "7.2.77", "7.2.77")],
                {"TELEGRAM_BOT_TOKEN": "test-token"},
            )

    def test_notify_sends_json_payload(self):
        response = io.BytesIO(b'{"ok": true}')
        output = io.StringIO()
        env = {
            "TELEGRAM_BOT_TOKEN": "test-token",
            "TELEGRAM_CHAT_ID": "-100123",
            "TELEGRAM_MESSAGE_THREAD_ID": "42",
            "GITHUB_REPOSITORY": "owner/repo",
            "GITHUB_RUN_ID": "123",
        }
        with patch.object(check_updates.urllib.request, "urlopen", return_value=response) as urlopen:
            with contextlib.redirect_stdout(output):
                sent = check_updates.notify_telegram([self.status("cpa", "7.2.76", "7.2.77")], env)

        self.assertTrue(sent)
        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["chat_id"], "-100123")
        self.assertEqual(payload["message_thread_id"], 42)
        self.assertIn("7.2.76 -> 7.2.77", payload["text"])
        self.assertNotIn("test-token", output.getvalue())

    def test_notify_deduplicates_same_update(self):
        response = io.BytesIO(b'{"ok": true}')
        with tempfile.TemporaryDirectory() as directory:
            env = {
                "TELEGRAM_BOT_TOKEN": "test-token",
                "TELEGRAM_CHAT_ID": "-100123",
                "TELEGRAM_STATE_FILE": str(Path(directory) / "state.json"),
            }
            with patch.object(check_updates.urllib.request, "urlopen", return_value=response) as urlopen:
                first = check_updates.notify_telegram([self.status("cpa", "7.2.76", "7.2.77")], env)
                second = check_updates.notify_telegram([self.status("cpa", "7.2.76", "7.2.77")], env)

            self.assertTrue(first)
            self.assertFalse(second)
            self.assertEqual(urlopen.call_count, 1)

    def test_notify_clears_state_when_all_apps_are_current(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state_path.write_text('{"version": 1, "updates": {"cpa": "old"}}', encoding="utf-8")
            sent = check_updates.notify_telegram(
                [self.status("cpa", "7.2.77", "7.2.77")],
                {"TELEGRAM_STATE_FILE": str(state_path)},
            )

            self.assertFalse(sent)
            self.assertFalse(state_path.exists())

    def test_notify_preserves_state_for_apps_with_check_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state_path.write_text(
                '{"version": 1, "updates": {"cpa": "notified-signature"}}',
                encoding="utf-8",
            )
            error_status = check_updates.UpdateStatus(
                "cpa", "", "", "", "", "", False, "TimeoutError: upstream"
            )

            sent = check_updates.notify_telegram(
                [error_status],
                {"TELEGRAM_STATE_FILE": str(state_path)},
            )

            self.assertFalse(sent)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["updates"], {"cpa": "notified-signature"})

    def test_telegram_test_notification_supports_thread(self):
        response = io.BytesIO(b'{"ok": true}')
        env = {
            "TELEGRAM_BOT_TOKEN": "test-token",
            "TELEGRAM_CHAT_ID": "-100123",
            "TELEGRAM_MESSAGE_THREAD_ID": "42",
        }
        with patch.object(check_updates.urllib.request, "urlopen", return_value=response) as urlopen:
            check_updates.send_telegram_test(env)

        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["message_thread_id"], 42)
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

    def test_failed_notification_does_not_advance_state(self):
        error = urllib.error.HTTPError(
            "https://api.telegram.org/bottest-token/sendMessage",
            500,
            "Internal Server Error",
            {},
            io.BytesIO(b'{"ok": false}'),
        )
        self.addCleanup(error.close)
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            original_state = '{"version": 1, "updates": {"cpa": "previous"}}'
            state_path.write_text(original_state, encoding="utf-8")
            env = {
                "TELEGRAM_BOT_TOKEN": "test-token",
                "TELEGRAM_CHAT_ID": "-100123",
                "TELEGRAM_STATE_FILE": str(state_path),
            }

            with patch.object(check_updates.urllib.request, "urlopen", side_effect=error):
                with self.assertRaisesRegex(RuntimeError, "HTTP 500"):
                    check_updates.notify_telegram(
                        [self.status("cpa", "7.2.75", "7.2.77")],
                        env,
                    )

            self.assertEqual(state_path.read_text(encoding="utf-8"), original_state)

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


if __name__ == "__main__":
    unittest.main()

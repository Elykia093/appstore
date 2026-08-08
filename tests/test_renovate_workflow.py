import json
import re
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
RENOVATE_APP_WORKFLOW = ROOT / ".github" / "workflows" / "renovate-app-version.yml"
RENOVATE_WORKFLOW = ROOT / ".github" / "workflows" / "renovate.yml"
CHECK_UPDATES_WORKFLOW = ROOT / ".github" / "workflows" / "check-updates.yml"
VALIDATE_WORKFLOW = ROOT / ".github" / "workflows" / "validate-appstore.yml"
WORKFLOWS_DIR = ROOT / ".github" / "workflows"
RENOVATE_CONFIG = ROOT / "renovate.json"
NEW_API_DIR = ROOT / "apps" / "new-api"


class RenovateWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        workflow = yaml.safe_load(RENOVATE_APP_WORKFLOW.read_text(encoding="utf-8"))
        cls.steps = workflow["jobs"]["update-app-version"]["steps"]

    @classmethod
    def step(cls, name: str):
        return next(step for step in cls.steps if step.get("name") == name)

    def test_self_generated_push_skips_duplicate_pr_processing(self):
        guard_script = self.step(
            "Check if triggered by self (prevent circular trigger)"
        )["run"]
        merge_step = self.step("Rebase to latest main and merge PR")

        self.assertIn('"$GITHUB_EVENT_NAME" == "workflow_dispatch"', guard_script)
        self.assertIn('echo "merge=false"', guard_script)
        self.assertIn('echo "merge=true"', guard_script)
        self.assertEqual(
            merge_step.get("if"),
            "steps.check-circular.outputs.merge == 'true' && github.ref_name != 'main'",
        )

    def test_merge_waits_for_pr_matching_current_head(self):
        merge_script = self.step("Rebase to latest main and merge PR")["run"]

        self.assertIn("max_pr_lookup_attempts", merge_script)
        self.assertIn("headRefOid", merge_script)
        self.assertIn(r"select(.headRefOid == \"$current_sha\")", merge_script)
        self.assertIn("Waiting for Renovate to create it", merge_script)
        self.assertIn("No open PR appeared", merge_script)

    def test_original_pr_exists_before_branch_transformation(self):
        wait_step = self.step("Wait for Renovate to create the original PR")
        wait_script = wait_step["run"]
        step_names = [step.get("name") for step in self.steps]

        self.assertEqual(
            wait_step.get("if"), "steps.check-circular.outputs.skip != 'true'"
        )
        self.assertLess(
            step_names.index("Wait for Renovate to create the original PR"),
            step_names.index("Run renovate-app-version.sh on updated files"),
        )
        self.assertLess(
            step_names.index("Wait for Renovate to create the original PR"),
            step_names.index("Commit & Push Changes"),
        )
        self.assertIn("original_sha=$(git rev-parse HEAD)", wait_script)
        self.assertIn(r'select(.headRefOid == \"$original_sha\")', wait_script)
        self.assertIn("Waiting for Renovate to create it", wait_script)
        self.assertIn("No open PR appeared", wait_script)

    def test_push_failures_are_not_suppressed(self):
        push_script = self.step("Commit & Push Changes")["run"]

        self.assertIn('git push origin "HEAD:$branch_name"', push_script)
        self.assertNotIn("|| echo", push_script)

    def test_merge_requires_validate_success_on_exact_head(self):
        merge_script = self.step("Rebase to latest main and merge PR")["run"]

        self.assertIn(
            'pr_head=$(gh pr view "$pr_number" --json headRefOid', merge_script
        )
        self.assertIn('select(.name == "validate")', merge_script)
        self.assertIn("validate_succeeded", merge_script)
        self.assertIn("FAILURE|CANCELLED|TIMED_OUT", merge_script)
        self.assertIn("within 10 minutes", merge_script)

    def test_merge_never_bypasses_branch_protection(self):
        merge_script = self.step("Rebase to latest main and merge PR")["run"]

        self.assertIn('--match-head-commit "$head_sha"', merge_script)
        self.assertNotIn("--admin", merge_script)
        self.assertIn("PR has conflicts; leaving it open", merge_script)

    def test_successful_merge_dispatches_next_renovate_run(self):
        merge_step = self.step("Rebase to latest main and merge PR")
        merge_script = merge_step["run"]

        self.assertEqual(merge_step["env"]["WORKFLOW_TOKEN"], "${{ github.token }}")
        self.assertIn(
            'GH_TOKEN="$WORKFLOW_TOKEN" gh workflow run renovate.yml --ref main',
            merge_script,
        )

    def test_merge_token_is_required_before_transformation(self):
        token_step = self.step("Require merge workflow token")

        self.assertEqual(
            token_step.get("if"), "steps.check-circular.outputs.merge == 'true'"
        )
        self.assertIn("MERGE_ADMIN_TOKEN is required", token_step["run"])


class SupportingWorkflowTests(unittest.TestCase):
    def test_all_actions_are_pinned_to_full_commit_shas(self):
        action_ref = re.compile(r"^\s*uses:\s+[^@\s]+@([^\s#]+)", re.MULTILINE)
        refs = []

        for workflow_path in sorted(WORKFLOWS_DIR.glob("*.yml")):
            refs.extend(action_ref.findall(workflow_path.read_text(encoding="utf-8")))

        self.assertTrue(refs)
        for ref in refs:
            with self.subTest(ref=ref):
                self.assertRegex(ref, r"^[0-9a-f]{40}$")

    def test_new_api_is_digest_pinned_in_config_and_compose(self):
        config = json.loads(RENOVATE_CONFIG.read_text(encoding="utf-8"))
        new_api_rules = [
            rule
            for rule in config["packageRules"]
            if "calciumion/new-api" in rule.get("matchPackageNames", [])
        ]
        version_dirs = sorted(
            path
            for path in NEW_API_DIR.iterdir()
            if path.is_dir() and path.name != "__pycache__"
        )

        self.assertEqual(len(version_dirs), 1)

        compose = yaml.safe_load(
            (version_dirs[0] / "docker-compose.yml").read_text(encoding="utf-8")
        )
        image = compose["services"]["new-api"]["image"]

        self.assertEqual(len(new_api_rules), 1)
        self.assertIs(new_api_rules[0].get("pinDigests"), True)
        self.assertRegex(image, r"@sha256:[0-9a-f]{64}$")

    def test_initial_renovate_opened_head_skips_transitional_validation(self):
        workflow = yaml.safe_load(VALIDATE_WORKFLOW.read_text(encoding="utf-8"))
        condition = workflow["jobs"]["validate"].get("if")

        self.assertEqual(
            condition,
            "${{ github.event_name != 'pull_request' || "
            "github.event.action != 'opened' || "
            "!startsWith(github.head_ref, 'renovate/') }}",
        )

    def test_renovate_runs_every_four_hours_and_uses_explicit_continuation(self):
        text = RENOVATE_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn('cron: "0 */4 * * *"', text)
        self.assertNotIn("  push:\n", text)
        self.assertNotIn("issues: write", text)

    def test_validation_is_read_only(self):
        text = VALIDATE_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("python scripts/sync-app-version-directories.py --check", text)
        self.assertNotIn("Normalize Renovate PR app versions", text)

    def test_update_notifications_cover_merge_and_daily_failures(self):
        text = CHECK_UPDATES_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("  push:\n", text)
        self.assertIn("--allow-stale", text)
        self.assertIn("--notify-merged", text)
        self.assertIn("github.event.before", text)
        self.assertNotIn("actions/cache", text)
        self.assertNotIn("TELEGRAM_STATE_FILE", text)


if __name__ == "__main__":
    unittest.main()

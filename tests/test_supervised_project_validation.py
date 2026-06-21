from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SESSION = ROOT / "projects/decodex/sessions/2026-06-21-v0.1.6-supervised-project-validation"
REVIEW = ROOT / "projects/decodex/skills/context-compliance-review/reviews/2026-06-21-v0.1.6-supervised-project-validation-review/review.yaml"
APPROVAL = ROOT / "projects/decodex/skills/context-compliance-review/approvals/2026-06-21-v0.1.6-supervised-project-validation-approval/approval.yaml"
EVALUATION = ROOT / "projects/decodex/skills/context-compliance-review/evaluations/2026-06-21-v0.1.6-supervised-project-validation-eval/evaluation.yaml"
SKILL = ROOT / "projects/decodex/skills/context-compliance-review/skill.yaml"
TRANSITIONS = ROOT / "projects/decodex/registry/skill-transition-history.jsonl"
CONTEXT = ROOT / "projects/decodex/.codex/project-context.md"


class SupervisedProjectValidationTests(unittest.TestCase):
    def test_v016_supervised_project_validation_cases(self) -> None:
        cases = [
            ("root_version", ROOT / "decodex.yaml", "version", "0.1.6"),
            ("gitignore_ci", ROOT / ".gitignore", "contains", ".decodex-ci/"),
            ("changelog_heading", ROOT / "CHANGELOG.md", "contains", "## v0.1.6 -- Supervised Project Validation"),
            ("schema_exists", ROOT / "schemas/skill-approval.schema.json", "exists", True),
            ("schema_decision", ROOT / "schemas/skill-approval.schema.json", "contains", "approve_project_validation"),
            ("session_exists", SESSION / "session.yaml", "exists", True),
            ("session_review", SESSION / "session.yaml", "contains", "2026-06-21-v0.1.6-supervised-project-validation-review"),
            ("session_approval", SESSION / "session.yaml", "contains", "2026-06-21-v0.1.6-supervised-project-validation-approval"),
            ("session_evals", SESSION / "session.yaml", "contains", "source-eval"),
            ("session_evals_2", SESSION / "session.yaml", "contains", "target-eval"),
            ("session_evals_3", SESSION / "session.yaml", "contains", "2026-06-21-v0.1.6-supervised-project-validation-eval"),
            ("review_exists", REVIEW, "exists", True),
            ("review_scope", REVIEW, "yaml", ("scope", "project")),
            ("review_status", REVIEW, "yaml", ("status", "candidate")),
            ("review_confidence", REVIEW, "yaml", ("confidence", "medium")),
            ("review_recommendation", REVIEW, "yaml", ("recommendation", "validate_project")),
            ("review_runs", REVIEW, "yaml", ("valid_runs", 3)),
            ("review_projects", REVIEW, "yaml_list_len", ("projects_tested", 2)),
            ("review_reuse", REVIEW, "yaml", ("cross_project_reuse", True)),
            ("review_contradictions", REVIEW, "yaml", ("unresolved_contradictions", 0)),
            ("approval_exists", APPROVAL, "exists", True),
            ("approval_decision", APPROVAL, "yaml", ("decision", "approve_project_validation")),
            ("approval_target_status", APPROVAL, "yaml", ("target_status", "validated")),
            ("approval_scope", APPROVAL, "yaml", ("scope", "project")),
            ("approval_review_confidence", APPROVAL, "yaml", ("review_confidence", "medium")),
            ("evaluation_exists", EVALUATION, "exists", True),
            ("skill_validated", SKILL, "yaml", ("status", "validated")),
            ("skill_scope", SKILL, "yaml", ("scope", "project")),
            ("skill_confidence", SKILL, "yaml", ("confidence", "medium")),
            ("transition_exists", TRANSITIONS, "exists", True),
            ("transition_global", TRANSITIONS, "contains", '"global":false'),
            ("context_note", CONTEXT, "contains", "validated for the `decodex` project, but it is not global"),
        ]

        for name, path, kind, expected in cases:
            with self.subTest(name=name):
                self.assertTrue(path.exists())
                if kind == "exists":
                    self.assertTrue(expected)
                elif kind == "contains":
                    self.assertIn(expected, path.read_text(encoding="utf-8"))
                elif kind == "yaml":
                    data = json.loads(path.read_text(encoding="utf-8"))
                    key, value = expected
                    self.assertEqual(data[key], value)
                elif kind == "yaml_list_len":
                    data = json.loads(path.read_text(encoding="utf-8"))
                    key, value = expected
                    self.assertEqual(len(data[key]), value)

    def test_transition_history_is_valid_jsonl(self) -> None:
        lines = [line for line in TRANSITIONS.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(lines), 1)
        event = json.loads(lines[0])
        self.assertEqual(event["skill_id"], "context-compliance-review")
        self.assertEqual(event["to_status"], "validated")
        self.assertEqual(event["scope"], "project")

    def test_context_and_session_live_in_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            copied = tmp_path / "session.yaml"
            copied.write_text(SESSION.joinpath("session.yaml").read_text(encoding="utf-8"), encoding="utf-8")
            self.assertTrue(copied.exists())
            self.assertIn("Record the third supervised project-validation pass", copied.read_text(encoding="utf-8"))

    def test_human_approval_metadata_is_present(self) -> None:
        skill = json.loads(SKILL.read_text(encoding="utf-8"))
        lifecycle = skill["lifecycle"]
        self.assertEqual(lifecycle["state"], "validated")
        self.assertEqual(lifecycle["approved_review"], "2026-06-21-v0.1.6-supervised-project-validation-review")
        self.assertEqual(lifecycle["approval"], "2026-06-21-v0.1.6-supervised-project-validation-approval")
        self.assertEqual(lifecycle["human_approval"], "approved")


if __name__ == "__main__":
    unittest.main()

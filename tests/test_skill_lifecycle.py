from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from decodex_core import (
    audit_repository,
    build_context,
    capture_session,
    context_check,
    load_jsonish,
    promote_skill,
    search_repository,
    session_close,
    skill_diff,
    skill_evaluate,
    skill_revise,
    skill_review,
    validate_repository,
)


class SkillLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temps: list[tempfile.TemporaryDirectory] = []

    def tearDown(self) -> None:
        for temp in self._temps:
            temp.cleanup()

    def make_repo(self, *, build_context_first: bool = False) -> Path:
        temp = tempfile.TemporaryDirectory()
        self._temps.append(temp)
        repo = Path(temp.name) / "Decodex"
        shutil.copytree(
            ROOT,
            repo,
            ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"),
        )
        if build_context_first:
            build_context(repo, project="decodex", output_root=repo)
        return repo

    def test_skill_lifecycle_matrix(self) -> None:
        cases = [
            ("baseline validation", self._case_baseline_validation),
            ("decision discovery", self._case_decision_discovery),
            ("context carries lifecycle", self._case_context_carries_lifecycle),
            ("session close preserves version", self._case_session_close_preserves_version),
            ("session close creates lifecycle artifacts", self._case_session_close_creates_artifacts),
            ("skill evaluation artifact", self._case_skill_evaluation_artifact),
            ("skill review artifact", self._case_skill_review_artifact),
            ("skill revision artifact", self._case_skill_revision_artifact),
            ("skill diff output", self._case_skill_diff_output),
            ("promotion initial copy", self._case_promotion_initial_copy),
            ("promotion force snapshot", self._case_promotion_force_snapshot),
            ("evaluation schema validation", self._case_evaluation_schema_validation),
            ("review schema validation", self._case_review_schema_validation),
            ("revision schema validation", self._case_revision_schema_validation),
            ("audit detects missing evidence", self._case_audit_missing_evidence),
            ("audit detects broken review", self._case_audit_broken_review),
            ("context check passes", self._case_context_check_passes),
            ("context check detects tamper", self._case_context_check_detects_tamper),
            ("search finds lifecycle skill", self._case_search_finds_skill),
            ("runtime contract still resolves", self._case_runtime_resolution),
        ]

        for name, case in cases:
            with self.subTest(case=name):
                case()

    def _case_baseline_validation(self) -> None:
        repo = self.make_repo(build_context_first=True)
        self.assertEqual(validate_repository(repo), [])
        self.assertEqual(audit_repository(repo), [])

    def _case_decision_discovery(self) -> None:
        repo = self.make_repo()
        extra_decision = repo / "projects" / "decodex" / "decisions" / "0002-lifecycle.json"
        extra_decision.write_text(
            json.dumps(
                {
                    "id": "0002-lifecycle",
                    "project": "decodex",
                    "summary": "Lifecycle decision",
                    "status": "validated",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        self.assertTrue(any("0001-supervised-self-improving-loop.json" in str(path) for path in search_repository(repo, "0001")))
        self.assertTrue(any("0002-lifecycle.json" in str(path) for path in search_repository(repo, "lifecycle")))
        self.assertEqual(validate_repository(repo), [])

    def _case_context_carries_lifecycle(self) -> None:
        repo = self.make_repo()
        session_close(
            repo,
            project="decodex",
            session="2026-06-20-v0.1.4-lifecycle-context",
            tests=["python -m unittest discover -s tests -v"],
            lessons=["lifecycle context must carry version and recommendation"],
            artifacts=["reports/lifecycle.md"],
        )
        context_dir = build_context(repo, project="decodex", output_root=repo)
        provenance = load_jsonish(context_dir / "provenance.json")
        project_skills = provenance["project_skills"]
        self.assertTrue(any(skill["version"] == "0.1.0" for skill in project_skills))
        self.assertTrue(any(skill["status"] == "validated" for skill in project_skills))
        self.assertTrue(any(skill["confidence"] == "medium" for skill in project_skills))
        self.assertTrue(any(skill["recommendation"] == "validate_project" for skill in project_skills))
        self.assertTrue(any(skill.get("latest_review") for skill in project_skills))

    def _case_session_close_preserves_version(self) -> None:
        repo = self.make_repo()
        skill_file = repo / "projects" / "decodex" / "skills" / "context-compliance-review" / "skill.yaml"
        original = load_jsonish(skill_file)
        session_close(
            repo,
            project="decodex",
            session="2026-06-20-v0.1.4-preserve-version",
            tests=["python -m unittest discover -s tests -v"],
            lessons=["session close should not reset the skill version"],
        )
        updated = load_jsonish(skill_file)
        self.assertEqual(updated["version"], original["version"])

    def _case_session_close_creates_artifacts(self) -> None:
        repo = self.make_repo()
        session_close(
            repo,
            project="decodex",
            session="2026-06-20-v0.1.4-artifacts",
            tests=["python -m unittest discover -s tests -v"],
            lessons=["append-only lifecycle artifacts"],
        )
        skill_dir = repo / "projects" / "decodex" / "skills" / "context-compliance-review"
        self.assertTrue((skill_dir / "evaluations" / "2026-06-20-v0.1.4-artifacts" / "evaluation.yaml").exists())
        self.assertTrue((skill_dir / "reviews" / "2026-06-20-v0.1.4-artifacts" / "review.yaml").exists())
        self.assertTrue((skill_dir / "versions" / "0.1.0" / "skill.yaml").exists())
        self.assertEqual(load_jsonish(skill_dir / "skill.yaml")["recommendation"], "validate_project")

    def _case_skill_evaluation_artifact(self) -> None:
        repo = self.make_repo()
        path = skill_evaluate(
            repo,
            skill_id="context-compliance-review",
            project="decodex",
            evaluation_id="eval-001",
            evidence=["projects/decodex/sessions/2026-06-20-v0.1.3-self-improving-development-loop/compliance-report.md"],
            notes=["first lifecycle evaluation"],
        )
        self.assertTrue(path.exists())
        self.assertEqual(load_jsonish(path)["recommendation"], "continue_evaluation")

    def _case_skill_review_artifact(self) -> None:
        repo = self.make_repo()
        skill_evaluate(
            repo,
            skill_id="context-compliance-review",
            project="decodex",
            evaluation_id="eval-002",
        )
        path = skill_review(
            repo,
            skill_id="context-compliance-review",
            project="decodex",
            review_id="review-001",
            evaluation_ids=["eval-002"],
            approved_by="human-reviewer",
        )
        self.assertTrue(path.exists())
        self.assertEqual(load_jsonish(path)["recommendation"], "continue_evaluation")

    def _case_skill_revision_artifact(self) -> None:
        repo = self.make_repo()
        skill_evaluate(
            repo,
            skill_id="context-compliance-review",
            project="decodex",
            evaluation_id="eval-003",
        )
        skill_review(
            repo,
            skill_id="context-compliance-review",
            project="decodex",
            review_id="review-003",
            evaluation_ids=["eval-003"],
            approved_by="human-reviewer",
        )
        skill_file, revision_file = skill_revise(
            repo,
            skill_id="context-compliance-review",
            project="decodex",
            revision_id="rev-001",
            to_version="0.1.1",
            status="experimental",
            summary="lift to the next revision",
            rationale="exercise revision path",
            evaluation_ids=["eval-003"],
        )
        self.assertTrue(skill_file.exists())
        self.assertTrue(revision_file.exists())
        self.assertEqual(load_jsonish(skill_file)["version"], "0.1.1")
        self.assertTrue((repo / "projects" / "decodex" / "skills" / "context-compliance-review" / "versions" / "0.1.1" / "skill.yaml").exists())

    def _case_skill_diff_output(self) -> None:
        repo = self.make_repo()
        skill_evaluate(repo, skill_id="context-compliance-review", project="decodex", evaluation_id="eval-004")
        skill_revise(
            repo,
            skill_id="context-compliance-review",
            project="decodex",
            revision_id="rev-004",
            to_version="0.1.1",
            status="experimental",
            summary="promote one step",
            rationale="version diff should be visible",
            evaluation_ids=["eval-004"],
        )
        diff = skill_diff(
            repo,
            skill_id="context-compliance-review",
            project="decodex",
            left_version="0.1.0",
            right_version="0.1.1",
        )
        self.assertIn("0.1.0", diff)
        self.assertIn("0.1.1", diff)

    def _case_promotion_initial_copy(self) -> None:
        repo = self.make_repo()
        source_dir, target_dir = promote_skill(
            repo,
            skill_id="context-compliance-review",
            from_scope="project",
            to_scope="global",
            project="decodex",
        )
        self.assertTrue(source_dir.exists())
        self.assertTrue(target_dir.exists())

    def _case_promotion_force_snapshot(self) -> None:
        repo = self.make_repo()
        promote_skill(
            repo,
            skill_id="context-compliance-review",
            from_scope="project",
            to_scope="global",
            project="decodex",
        )
        _, snapshot = promote_skill(
            repo,
            skill_id="context-compliance-review",
            from_scope="project",
            to_scope="global",
            project="decodex",
            force=True,
        )
        self.assertTrue((repo / "global" / "skills" / "context-compliance-review" / "skill.yaml").exists())
        self.assertEqual(snapshot.parent.name, "versions")

    def _case_evaluation_schema_validation(self) -> None:
        repo = self.make_repo()
        evaluation_path = skill_evaluate(
            repo,
            skill_id="context-compliance-review",
            project="decodex",
            evaluation_id="eval-005",
        )
        self.assertEqual(validate_repository(repo), [])
        self.assertEqual(load_jsonish(evaluation_path)["skill_id"], "context-compliance-review")

    def _case_review_schema_validation(self) -> None:
        repo = self.make_repo()
        skill_evaluate(repo, skill_id="context-compliance-review", project="decodex", evaluation_id="eval-006")
        review_path = skill_review(
            repo,
            skill_id="context-compliance-review",
            project="decodex",
            review_id="review-006",
            evaluation_ids=["eval-006"],
            recommendation="project_validated",
        )
        self.assertEqual(validate_repository(repo), [])
        self.assertEqual(load_jsonish(review_path)["reviewer"], "decodex")

    def _case_revision_schema_validation(self) -> None:
        repo = self.make_repo()
        skill_evaluate(repo, skill_id="context-compliance-review", project="decodex", evaluation_id="eval-007")
        skill_review(
            repo,
            skill_id="context-compliance-review",
            project="decodex",
            review_id="review-007",
            evaluation_ids=["eval-007"],
        )
        _, revision_path = skill_revise(
            repo,
            skill_id="context-compliance-review",
            project="decodex",
            revision_id="rev-007",
            to_version="0.1.1",
            evaluation_ids=["eval-007"],
        )
        self.assertEqual(validate_repository(repo), [])
        self.assertEqual(load_jsonish(revision_path)["status"], "applied")

    def _case_audit_missing_evidence(self) -> None:
        repo = self.make_repo()
        evaluation_path = skill_evaluate(
            repo,
            skill_id="context-compliance-review",
            project="decodex",
            evaluation_id="eval-008",
            evidence=["projects/decodex/missing-evidence.md"],
        )
        errors = audit_repository(repo)
        self.assertTrue(any("missing evidence file" in error for error in errors))
        self.assertTrue(evaluation_path.exists())

    def _case_audit_broken_review(self) -> None:
        repo = self.make_repo()
        skill_evaluate(repo, skill_id="context-compliance-review", project="decodex", evaluation_id="eval-009")
        review_path = skill_review(
            repo,
            skill_id="context-compliance-review",
            project="decodex",
            review_id="review-009",
            evaluation_ids=["eval-009"],
        )
        review_data = load_jsonish(review_path)
        review_data["evaluation_ids"] = ["missing-eval"]
        review_path.write_text(json.dumps(review_data, indent=2) + "\n", encoding="utf-8")
        errors = audit_repository(repo)
        self.assertTrue(any("missing referenced evaluation" in error for error in errors))

    def _case_context_check_passes(self) -> None:
        repo = self.make_repo()
        build_context(repo, project="decodex", output_root=repo)
        self.assertEqual(context_check(repo, project="decodex"), [])

    def _case_context_check_detects_tamper(self) -> None:
        repo = self.make_repo()
        context_dir = build_context(repo, project="decodex", output_root=repo)
        tampered = context_dir / "project-context.md"
        tampered.write_text(tampered.read_text(encoding="utf-8") + "\n- tampered\n", encoding="utf-8")
        errors = context_check(repo, project="decodex")
        self.assertTrue(any("context diverges" in error or "stale" in error for error in errors))

    def _case_search_finds_skill(self) -> None:
        repo = self.make_repo()
        self.assertTrue(any("context-compliance-review" in str(path) for path in search_repository(repo, "Context Compliance Review")))
        self.assertTrue(any("provenance" in str(path) for path in search_repository(repo, "provenance")))

    def _case_runtime_resolution(self) -> None:
        repo = self.make_repo()
        self.assertTrue((repo / "decodex.yaml").exists())
        self.assertEqual(load_jsonish(repo / "decodex.yaml")["version"], "0.1.6")


if __name__ == "__main__":
    unittest.main()

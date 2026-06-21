from __future__ import annotations

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
    context_check,
    load_jsonish,
    search_repository,
    skill_promotion_candidate,
    skill_promotion_review,
    skill_review,
    validate_repository,
)


class GlobalPromotionReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temps: list[tempfile.TemporaryDirectory] = []
        self._prepared_repo: Path | None = None
        self._prepared_artifacts: dict[str, Path] | None = None

    def tearDown(self) -> None:
        for temp in self._temps:
            temp.cleanup()

    def make_repo(self) -> Path:
        temp = tempfile.TemporaryDirectory()
        self._temps.append(temp)
        repo = Path(temp.name) / "Decodex"
        shutil.copytree(
            ROOT,
            repo,
            ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"),
        )
        return repo

    def prepared_repo(self) -> tuple[Path, dict[str, Path]]:
        if self._prepared_repo is not None and self._prepared_artifacts is not None:
            return self._prepared_repo, self._prepared_artifacts

        repo = self.make_repo()
        review = skill_review(
            repo,
            skill_id="context-compliance-review",
            project="decodex",
            review_id="2026-06-21-v0.1.7-global-promotion-readiness-test-review",
            evaluation_ids=[
                "source-eval",
                "target-eval",
                "2026-06-21-v0.1.6-supervised-project-validation-eval",
                "2026-06-21-v0.1.7-surepython-reuse-eval",
                "2026-06-21-v0.1.7-local-confirmation-eval",
            ],
            recommendation="promote_global",
            confidence="high",
            notes=["test readiness review"],
        )
        candidate, candidate_report = skill_promotion_candidate(
            repo,
            project="decodex",
            skill_id="context-compliance-review",
            candidate_id="2026-06-21-v0.1.7-global-promotion-readiness-test",
            review_id="2026-06-21-v0.1.7-global-promotion-readiness-test-review",
        )
        human_review, human_report = skill_promotion_review(
            repo,
            project="decodex",
            skill_id="context-compliance-review",
            candidate_id="2026-06-21-v0.1.7-global-promotion-readiness-test",
            review_id="2026-06-21-v0.1.7-global-promotion-readiness-human-test",
            decision="approve_global_promotion",
            reviewer="Codex",
            rationale="global promotion readiness is supported by explicit evidence",
        )

        build_context(repo, project="decodex", output_root=repo)
        build_context(repo, project="pac-hunt-2", output_root=repo / "projects" / "pac-hunt-2")
        build_context(repo, project="surepython", output_root=repo / "projects" / "surepython")

        artifacts = {
            "review": review,
            "candidate": candidate,
            "candidate_report": candidate_report,
            "human_review": human_review,
            "human_report": human_report,
        }
        self._prepared_repo = repo
        self._prepared_artifacts = artifacts
        return repo, artifacts

    def test_global_promotion_readiness_matrix(self) -> None:
        cases = [
            ("validation passes", self._case_validation_passes),
            ("audit passes", self._case_audit_passes),
            ("review aggregates five runs", self._case_review_valid_runs),
            ("review keeps success rate cautious", self._case_review_success_rate),
            ("review spans three projects", self._case_review_projects),
            ("review records reuse counts", self._case_review_reuse_counts),
            ("review keeps contradictions clear", self._case_review_contradictions),
            ("review recommends global promotion", self._case_review_recommendation),
            ("candidate dossier is written", self._case_candidate_written),
            ("candidate remains pending", self._case_candidate_pending),
            ("candidate keeps immutable metrics", self._case_candidate_metrics),
            ("human review is separate", self._case_human_review_separate),
            ("human review does not publish globally", self._case_human_review_no_publish),
            ("decodex context exposes readiness", self._case_decodex_context_readiness),
            ("decodex context check passes", self._case_decodex_context_check),
            ("surepython context check passes", self._case_surepython_context_check),
            ("pac-hunt-2 context check passes", self._case_pac_hunt_context_check),
            ("search finds candidate", self._case_search_candidate),
            ("search finds review", self._case_search_review),
            ("no global skill copy exists", self._case_no_global_copy),
        ]

        for name, case in cases:
            with self.subTest(case=name):
                case()

    def _prepared(self) -> tuple[Path, dict[str, Path]]:
        return self.prepared_repo()

    def _candidate_file(self) -> Path:
        repo, _ = self._prepared()
        return repo / "projects" / "decodex" / "skills" / "context-compliance-review" / "promotion-candidates" / "2026-06-21-v0.1.7-global-promotion-readiness-test" / "candidate.yaml"

    def _review_file(self) -> Path:
        repo, _ = self._prepared()
        return repo / "projects" / "decodex" / "skills" / "context-compliance-review" / "reviews" / "2026-06-21-v0.1.7-global-promotion-readiness-test-review" / "review.yaml"

    def _context_file(self) -> Path:
        repo, _ = self._prepared()
        return repo / ".codex" / "project-context.md"

    def _case_validation_passes(self) -> None:
        repo, _ = self._prepared()
        self.assertEqual(validate_repository(repo), [])

    def _case_audit_passes(self) -> None:
        repo, _ = self._prepared()
        self.assertEqual(audit_repository(repo), [])

    def _case_review_valid_runs(self) -> None:
        review = load_jsonish(self._review_file())
        self.assertEqual(review["valid_runs"], 5)
        self.assertEqual(review["successful_evaluations"], 4)

    def _case_review_success_rate(self) -> None:
        review = load_jsonish(self._review_file())
        self.assertEqual(review["success_rate"], 0.8)

    def _case_review_projects(self) -> None:
        review = load_jsonish(self._review_file())
        self.assertEqual(review["independent_projects"], 3)
        self.assertEqual(review["projects_tested"], ["decodex", "pac-hunt-2", "surepython"])

    def _case_review_reuse_counts(self) -> None:
        review = load_jsonish(self._review_file())
        self.assertTrue(review["cross_project_reuse"])
        self.assertEqual(review["independent_reuses"], 2)
        self.assertEqual(review["unresolved_contradictions"], 0)
        self.assertEqual(review["safety_failures"], 0)

    def _case_review_contradictions(self) -> None:
        review = load_jsonish(self._review_file())
        self.assertEqual(review["divergences"], ["confidence levels observed: low, medium"])
        self.assertIn("conflicting recommendations", review["contradictions"][0])

    def _case_review_recommendation(self) -> None:
        review = load_jsonish(self._review_file())
        self.assertEqual(review["recommendation"], "promote_global")
        self.assertEqual(review["confidence"], "high")

    def _case_candidate_written(self) -> None:
        candidate = load_jsonish(self._candidate_file())
        self.assertEqual(candidate["skill_id"], "context-compliance-review")
        self.assertEqual(candidate["report_path"].endswith("report.md"), True)

    def _case_candidate_pending(self) -> None:
        candidate = load_jsonish(self._candidate_file())
        self.assertEqual(candidate["human_decision"], "pending")
        self.assertFalse(candidate["promotion_executed"])

    def _case_candidate_metrics(self) -> None:
        candidate = load_jsonish(self._candidate_file())
        self.assertEqual(candidate["valid_runs"], 5)
        self.assertEqual(candidate["success_rate"], 0.8)
        self.assertEqual(candidate["independent_projects"], 3)
        self.assertEqual(candidate["independent_reuses"], 2)
        self.assertTrue(candidate["cross_project_reuse"])

    def _case_human_review_separate(self) -> None:
        human_review = load_jsonish(self._prepared()[1]["human_review"])
        self.assertEqual(human_review["decision"], "approve_global_promotion")
        self.assertEqual(human_review["decision_status"], "global_promotion_ready")

    def _case_human_review_no_publish(self) -> None:
        human_review = load_jsonish(self._prepared()[1]["human_review"])
        self.assertFalse(human_review["promotion_executed"])
        self.assertNotIn("global/skills/context-compliance-review", str(human_review["evidence"]))

    def _case_decodex_context_readiness(self) -> None:
        context_text = self._context_file().read_text(encoding="utf-8")
        self.assertIn("## Global Promotion Readiness", context_text)
        self.assertIn("status: global_promotion_ready", context_text)
        self.assertIn("success_rate: 0.8", context_text)

    def _case_decodex_context_check(self) -> None:
        repo, _ = self._prepared()
        self.assertEqual(context_check(repo, project="decodex", context_root=repo), [])

    def _case_surepython_context_check(self) -> None:
        repo, _ = self._prepared()
        self.assertEqual(context_check(repo, project="surepython", context_root=repo / "projects" / "surepython"), [])

    def _case_pac_hunt_context_check(self) -> None:
        repo, _ = self._prepared()
        self.assertEqual(context_check(repo, project="pac-hunt-2", context_root=repo / "projects" / "pac-hunt-2"), [])

    def _case_search_candidate(self) -> None:
        repo, _ = self._prepared()
        matches = search_repository(repo, "global-promotion-readiness-test")
        self.assertTrue(any("promotion-candidates" in str(path) for path in matches))

    def _case_search_review(self) -> None:
        repo, _ = self._prepared()
        matches = search_repository(repo, "promote_global")
        self.assertTrue(any("reviews" in str(path) for path in matches))

    def _case_no_global_copy(self) -> None:
        repo, _ = self._prepared()
        self.assertFalse((repo / "global" / "skills" / "context-compliance-review" / "skill.yaml").exists())


if __name__ == "__main__":
    unittest.main()

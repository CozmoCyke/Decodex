from __future__ import annotations

import json
import hashlib
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
    skill_apply,
    skill_evaluate,
    skill_review,
    validate_repository,
)


class CrossProjectReuseTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temps: list[tempfile.TemporaryDirectory] = []

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
        self._remove_tree(repo / "projects" / "decodex" / "sessions" / "2026-06-20-v0.1.5-cross-project-reuse")
        self._remove_tree(repo / "projects" / "decodex" / "sessions" / "2026-06-20-v0.1.5-cross-project-reuse-source")
        self._remove_tree(repo / "projects" / "decodex" / "skills" / "context-compliance-review" / "evaluations" / "source-eval")
        self._remove_tree(repo / "projects" / "pac-hunt-2" / "sessions" / "2026-06-20-v0.1.5-cross-project-reuse")
        self._remove_tree(repo / "projects" / "pac-hunt-2" / "skills" / "context-compliance-review")
        self._remove_tree(repo / "projects" / "pac-hunt-2" / ".codex")
        self._remove_tree(repo / ".codex")
        return repo.resolve()

    def _remove_tree(self, path: Path) -> None:
        if path.exists():
            shutil.rmtree(path)

    def _write_jsonish(self, path: Path, data: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    def _write_session_bundle(self, repo: Path, *, project: str, session: str, goal: str, summary: str) -> Path:
        session_dir = repo / "projects" / project / "sessions" / session
        session_dir.mkdir(parents=True, exist_ok=True)
        self._write_jsonish(
            session_dir / "session.yaml",
            {
                "id": session,
                "project": project,
                "date": "2026-06-20",
                "goal": goal,
            },
        )
        (session_dir / "compliance-report.md").write_text(
            "\n".join(
                [
                    "# Compliance Report",
                    "",
                    f"- project: {project}",
                    f"- session: {session}",
                    f"- summary: {summary}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        self._write_jsonish(
            session_dir / "feedback.yaml",
            {
                "context_feedback": {
                    "useful_rules": [summary],
                    "missing_rules": [],
                    "ambiguous_rules": [],
                    "skill_candidates": ["context-compliance-review"],
                }
            },
        )
        return session_dir

    def _seed_pilot(self, repo: Path) -> dict[str, Path | str]:
        source_session = "2026-06-20-v0.1.5-cross-project-reuse-source"
        target_session = "2026-06-20-v0.1.5-cross-project-reuse"
        source_session_dir = self._write_session_bundle(
            repo,
            project="decodex",
            session=source_session,
            goal="Document the source evidence used to validate cross-project reuse.",
            summary="source context stays cautious",
        )
        target_session_dir = self._write_session_bundle(
            repo,
            project="pac-hunt-2",
            session=target_session,
            goal="Apply the Decodex skill to Pac-Hunt 2 without changing the source skill.",
            summary="target project uses the reused skill",
        )

        application_path, application_report = skill_apply(
            repo,
            skill_id="context-compliance-review",
            from_project="decodex",
            to_project="pac-hunt-2",
            session=target_session,
        )

        source_eval = skill_evaluate(
            repo,
            skill_id="context-compliance-review",
            project="decodex",
            evaluation_id="source-eval",
            session=source_session,
            evidence=[(source_session_dir / "compliance-report.md").relative_to(repo).as_posix()],
            notes=["source project evidence"],
        )

        target_eval = skill_evaluate(
            repo,
            skill_id="context-compliance-review",
            project="pac-hunt-2",
            evaluation_id="target-eval",
            session=target_session,
            application_id=load_jsonish(application_path)["id"],
            application_path=application_path.relative_to(repo).as_posix(),
            source_project="decodex",
            target_project="pac-hunt-2",
            evidence=[
                source_session_dir.joinpath("compliance-report.md").relative_to(repo).as_posix(),
                target_session_dir.joinpath("compliance-report.md").relative_to(repo).as_posix(),
                "projects/pac-hunt-2/reports/PACHUNT2_PERFORMANCE_FIX_REPORT.md",
                application_report.relative_to(repo).as_posix(),
            ],
            notes=["cross-project reuse pilot"],
        )

        review = skill_review(
            repo,
            skill_id="context-compliance-review",
            project="pac-hunt-2",
            review_id="cross-project-review",
            evaluation_ids=["source-eval", "target-eval"],
            recommendation="continue_evaluation",
            confidence="low",
            approved_by="human-reviewer",
            notes=["reuse remains deliberately cautious"],
        )

        pac_context = build_context(repo, project="pac-hunt-2", output_root=repo / "projects" / "pac-hunt-2")
        return {
            "source_session": source_session,
            "target_session": target_session,
            "source_session_dir": source_session_dir,
            "target_session_dir": target_session_dir,
            "application_path": application_path,
            "application_report": application_report,
            "source_eval": source_eval,
            "target_eval": target_eval,
            "review": review,
            "pac_context": pac_context,
            "application_id": load_jsonish(application_path)["id"],
        }

    def test_cross_project_reuse_matrix(self) -> None:
        cases = [
            ("application artifact created", self._case_application_artifact_created),
            ("duplicate application rejected", self._case_duplicate_application_rejected),
            ("missing source skill rejected", self._case_missing_source_skill_rejected),
            ("missing target project rejected", self._case_missing_target_project_rejected),
            ("application hash recorded", self._case_application_hash_recorded),
            ("target context lists applied skills", self._case_target_context_lists_applied_skills),
            ("target context check passes", self._case_target_context_check_passes),
            ("source evaluation links to session", self._case_source_evaluation_links_to_session),
            ("target evaluation links to application", self._case_target_evaluation_links_to_application),
            ("review aggregates two projects", self._case_review_aggregates_two_projects),
            ("review stays cautious", self._case_review_stays_cautious),
            ("validate accepts application schema", self._case_validate_accepts_application_schema),
            ("audit passes for healthy pilot", self._case_audit_passes_for_healthy_pilot),
            ("audit detects tampered source hash", self._case_audit_detects_tampered_source_hash),
            ("audit detects duplicate application id", self._case_audit_detects_duplicate_application_id),
            ("audit detects mixed versions", self._case_audit_detects_mixed_versions),
            ("context check detects tamper", self._case_context_check_detects_tamper),
            ("search reaches application context", self._case_search_reaches_application_context),
        ]

        for name, case in cases:
            with self.subTest(case=name):
                case()

    def _case_application_artifact_created(self) -> None:
        repo = self.make_repo()
        data = self._seed_pilot(repo)
        application = load_jsonish(data["application_path"])
        self.assertEqual(application["status"], "applied")
        self.assertEqual(application["source_project"], "decodex")
        self.assertEqual(application["target_project"], "pac-hunt-2")
        self.assertTrue(data["application_path"].exists())
        self.assertTrue(data["application_report"].exists())

    def _case_duplicate_application_rejected(self) -> None:
        repo = self.make_repo()
        data = self._seed_pilot(repo)
        with self.assertRaises(Exception):
            skill_apply(
                repo,
                skill_id="context-compliance-review",
                from_project="decodex",
                to_project="pac-hunt-2",
                session=data["target_session"],
            )

    def _case_missing_source_skill_rejected(self) -> None:
        repo = self.make_repo()
        (repo / "projects" / "decodex" / "skills" / "context-compliance-review" / "skill.yaml").unlink()
        self._write_session_bundle(
            repo,
            project="pac-hunt-2",
            session="2026-06-20-v0.1.5-cross-project-reuse",
            goal="Apply the Decodex skill to Pac-Hunt 2 without changing the source skill.",
            summary="target project uses the reused skill",
        )
        with self.assertRaises(Exception):
            skill_apply(
                repo,
                skill_id="context-compliance-review",
                from_project="decodex",
                to_project="pac-hunt-2",
                session="2026-06-20-v0.1.5-cross-project-reuse",
            )

    def _case_missing_target_project_rejected(self) -> None:
        repo = self.make_repo()
        (repo / "projects" / "pac-hunt-2" / "project.yaml").unlink()
        with self.assertRaises(Exception):
            skill_apply(
                repo,
                skill_id="context-compliance-review",
                from_project="decodex",
                to_project="pac-hunt-2",
                session="2026-06-20-v0.1.5-cross-project-reuse",
            )

    def _case_application_hash_recorded(self) -> None:
        repo = self.make_repo()
        data = self._seed_pilot(repo)
        application = load_jsonish(data["application_path"])
        source_skill_path = repo / application["source_skill_path"]
        expected_hash = hashlib.sha256(source_skill_path.read_bytes()).hexdigest()
        self.assertEqual(application["source_hash"], expected_hash)

    def _case_target_context_lists_applied_skills(self) -> None:
        repo = self.make_repo()
        data = self._seed_pilot(repo)
        project_context = (data["pac_context"] / "project-context.md").read_text(encoding="utf-8")
        self.assertIn("Applied Project Skills", project_context)
        self.assertIn("application=", project_context)
        self.assertIn("origin=decodex", project_context)

    def _case_target_context_check_passes(self) -> None:
        repo = self.make_repo()
        data = self._seed_pilot(repo)
        self.assertEqual(context_check(repo, project="pac-hunt-2", context_root=repo / "projects" / "pac-hunt-2"), [])

    def _case_source_evaluation_links_to_session(self) -> None:
        repo = self.make_repo()
        data = self._seed_pilot(repo)
        evaluation = load_jsonish(data["source_eval"])
        self.assertEqual(evaluation["session"], data["source_session"])
        self.assertEqual(evaluation["project"], "decodex")

    def _case_target_evaluation_links_to_application(self) -> None:
        repo = self.make_repo()
        data = self._seed_pilot(repo)
        evaluation = load_jsonish(data["target_eval"])
        self.assertEqual(evaluation["session"], data["target_session"])
        self.assertEqual(evaluation["application_id"], data["application_id"])
        self.assertEqual(evaluation["source_project"], "decodex")
        self.assertEqual(evaluation["target_project"], "pac-hunt-2")

    def _case_review_aggregates_two_projects(self) -> None:
        repo = self.make_repo()
        data = self._seed_pilot(repo)
        review = load_jsonish(data["review"])
        self.assertEqual(review["projects_tested"], ["decodex", "pac-hunt-2"])
        self.assertEqual(review["independent_projects"], 2)
        self.assertEqual(review["applications_considered"], 2)
        self.assertTrue(review["cross_project_reuse"])

    def _case_review_stays_cautious(self) -> None:
        repo = self.make_repo()
        data = self._seed_pilot(repo)
        review = load_jsonish(data["review"])
        self.assertEqual(review["confidence"], "low")
        self.assertEqual(review["recommendation"], "continue_evaluation")
        self.assertEqual(review["skill_version"], "0.1.0")

    def _case_validate_accepts_application_schema(self) -> None:
        repo = self.make_repo()
        self._seed_pilot(repo)
        self.assertEqual(validate_repository(repo), [])

    def _case_audit_passes_for_healthy_pilot(self) -> None:
        repo = self.make_repo()
        self._seed_pilot(repo)
        self.assertEqual(audit_repository(repo), [])

    def _case_audit_detects_tampered_source_hash(self) -> None:
        repo = self.make_repo()
        data = self._seed_pilot(repo)
        application = load_jsonish(data["application_path"])
        application["source_hash"] = "bad-hash"
        data["application_path"].write_text(json.dumps(application, indent=2) + "\n", encoding="utf-8")
        errors = audit_repository(repo)
        self.assertTrue(any("source hash mismatch" in error for error in errors))

    def _case_audit_detects_duplicate_application_id(self) -> None:
        repo = self.make_repo()
        data = self._seed_pilot(repo)
        duplicate_dir = repo / "projects" / "pac-hunt-2" / "sessions" / "2026-06-20-v0.1.5-cross-project-reuse-copy" / "skill-applications" / data["application_id"]
        duplicate_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(data["application_path"], duplicate_dir / "application.yaml")
        shutil.copy2(data["application_report"], duplicate_dir / "report.md")
        errors = audit_repository(repo)
        self.assertTrue(any("duplicate application id" in error for error in errors))

    def _case_audit_detects_mixed_versions(self) -> None:
        repo = self.make_repo()
        data = self._seed_pilot(repo)
        evaluation = load_jsonish(data["target_eval"])
        evaluation["skill_version"] = "9.9.9"
        data["target_eval"].write_text(json.dumps(evaluation, indent=2) + "\n", encoding="utf-8")
        errors = audit_repository(repo)
        self.assertTrue(any("version mismatch" in error for error in errors))

    def _case_context_check_detects_tamper(self) -> None:
        repo = self.make_repo()
        data = self._seed_pilot(repo)
        tampered = data["pac_context"] / "project-context.md"
        tampered.write_text(tampered.read_text(encoding="utf-8") + "\n- tampered\n", encoding="utf-8")
        errors = context_check(repo, project="pac-hunt-2", context_root=repo / "projects" / "pac-hunt-2")
        self.assertTrue(any("context diverges" in error or "stale" in error for error in errors))

    def _case_search_reaches_application_context(self) -> None:
        repo = self.make_repo()
        data = self._seed_pilot(repo)
        self.assertTrue((data["pac_context"] / "inherited-skills.md").exists())
        self.assertTrue((data["pac_context"] / "provenance.json").exists())


if __name__ == "__main__":
    unittest.main()

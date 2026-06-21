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
    context_check,
    init_project,
    load_jsonish,
    skill_apply,
    _sha256_file,
    _sha256_portable_file,
)


class CrossPlatformHashingTests(unittest.TestCase):
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
        return repo

    def _to_crlf(self, path: Path) -> None:
        raw = path.read_bytes()
        if b"\r\n" in raw:
            return
        path.write_bytes(raw.replace(b"\n", b"\r\n"))

    def test_cross_platform_hashing_matrix(self) -> None:
        cases = [
            ("portable hash matches for lf and crlf", self._case_portable_hash_matches),
            ("raw hash differs for lf and crlf", self._case_raw_hash_differs),
            ("application survives line ending conversion", self._case_application_survives_conversion),
            ("context check survives line ending conversion", self._case_context_check_survives_conversion),
            ("real text change is detected", self._case_real_text_change_detected),
            ("binary files use raw bytes", self._case_binary_uses_raw_bytes),
            ("legacy artifacts remain valid", self._case_legacy_artifacts_remain_valid),
            ("new artifacts declare portable mode", self._case_new_artifacts_declare_portable_mode),
        ]

        for name, case in cases:
            with self.subTest(case=name):
                case()

    def _case_portable_hash_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            lf = base / "sample.yaml"
            crlf = base / "sample-crlf.yaml"
            lf.write_text("alpha\nbeta\n", encoding="utf-8")
            crlf.write_bytes(b"alpha\r\nbeta\r\n")
            self.assertEqual(_sha256_portable_file(lf), _sha256_portable_file(crlf))

    def _case_raw_hash_differs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            lf = base / "sample.yaml"
            crlf = base / "sample-crlf.yaml"
            lf.write_bytes(b"alpha\nbeta\n")
            crlf.write_bytes(b"alpha\r\nbeta\r\n")
            self.assertNotEqual(_sha256_file(lf), _sha256_file(crlf))

    def _case_application_survives_conversion(self) -> None:
        repo = self.make_repo()
        init_project(repo, "hashing-target")
        skill_apply(
            repo,
            skill_id="context-compliance-review",
            from_project="decodex",
            to_project="hashing-target",
            session="2026-06-21-v0.1.7-cross-platform-hash",
        )
        source_skill = repo / "projects" / "decodex" / "skills" / "context-compliance-review" / "skill.yaml"
        self._to_crlf(source_skill)
        self.assertEqual(audit_repository(repo), [])

    def _case_context_check_survives_conversion(self) -> None:
        repo = self.make_repo()
        build_context(repo, project="decodex", output_root=repo)
        source_file = repo / "projects" / "decodex" / "skills" / "context-compliance-review" / "evaluations" / "source-eval" / "evaluation.yaml"
        self._to_crlf(source_file)
        self.assertEqual(context_check(repo, project="decodex", context_root=repo), [])

    def _case_real_text_change_detected(self) -> None:
        repo = self.make_repo()
        skill_file = repo / "projects" / "decodex" / "skills" / "context-compliance-review" / "skill.yaml"
        skill = load_jsonish(skill_file)
        skill["title"] = "Context Compliance Review Updated"
        skill_file.write_text(json.dumps(skill, indent=2) + "\n", encoding="utf-8")
        errors = audit_repository(repo)
        self.assertTrue(any("source hash mismatch" in error or "stale source hash" in error for error in errors))

    def _case_binary_uses_raw_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            binary_file = Path(tmp) / "payload.bin"
            binary_file.write_bytes(b"\x00\x01\x02binary-data\xff")
            self.assertEqual(_sha256_file(binary_file), _sha256_portable_file(binary_file))

    def _case_legacy_artifacts_remain_valid(self) -> None:
        repo = self.make_repo()
        application = load_jsonish(
            repo
            / "projects"
            / "decodex"
            / "sessions"
            / "2026-06-21-v0.1.6-supervised-project-validation"
            / "skill-applications"
            / "context-compliance-review--decodex--decodex--2026-06-21-v0.1.6-supervised-project-validation--0.1.0"
            / "application.yaml"
        )
        self.assertNotIn("source_hash_mode", application)
        self.assertEqual(audit_repository(repo), [])

    def _case_new_artifacts_declare_portable_mode(self) -> None:
        repo = self.make_repo()
        init_project(repo, "hashing-target")
        application_path, _ = skill_apply(
            repo,
            skill_id="context-compliance-review",
            from_project="decodex",
            to_project="hashing-target",
            session="2026-06-21-v0.1.7-new-portable-mode",
        )
        application = load_jsonish(application_path)
        self.assertEqual(application["source_hash_algorithm"], "sha256")
        self.assertEqual(application["source_hash_mode"], "normalized-text-lf-v1")
        build_context(repo, project="hashing-target", output_root=repo / "projects" / "hashing-target")
        provenance = load_jsonish(repo / "projects" / "hashing-target" / ".codex" / "provenance.json")
        self.assertEqual(provenance["hash_policy"]["algorithm"], "sha256")
        self.assertEqual(provenance["hash_policy"]["text_normalization"], "lf-v1")


if __name__ == "__main__":
    unittest.main()

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
    DecodexError,
    build_context,
    capture_session,
    context_check,
    init_project,
    init_workspace,
    load_jsonish,
    resolve_python_interpreter,
    search_repository,
    session_close,
    validate_repository,
)


class ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "Decodex"
        shutil.copytree(
            ROOT,
            self.root,
            ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"),
        )
        build_context(self.root, project="decodex", output_root=self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_repository_contract_validates(self) -> None:
        self.assertEqual(validate_repository(self.root), [])
        self.assertEqual(audit_repository(self.root), [])
        self.assertEqual(context_check(self.root, project="decodex"), [])

    def test_bootstrap_session_fixture_is_present(self) -> None:
        session = load_jsonish(
            self.root / "projects" / "decodex" / "sessions" / "2026-06-20-bootstrap-v0.1" / "session.yaml"
        )
        self.assertEqual(session["project"], "decodex")
        self.assertTrue(
            any(
                "contract tests before expanding a CLI" in item
                or "contract-first validation" in item
                for item in session["lessons"]["global_candidates"]
            )
        )

    def test_invalid_jsonish_and_duplicate_keys_fail_cleanly(self) -> None:
        bad_file = self.root / "bad.yaml"
        bad_file.write_text('{"a": 1, "a": 2}', encoding="utf-8")
        with self.assertRaises(DecodexError):
            load_jsonish(bad_file)

        bad_file.write_text('{"a": ', encoding="utf-8")
        with self.assertRaises(DecodexError):
            load_jsonish(bad_file)

        with self.assertRaises(DecodexError):
            load_jsonish(self.root / "missing.yaml")

    def test_python_resolution_uses_configured_path(self) -> None:
        fake_python = self.root / "tmp-bin" / "python.exe"
        fake_python.parent.mkdir(parents=True, exist_ok=True)
        fake_python.write_text("", encoding="utf-8")

        resolved = resolve_python_interpreter(self.root, {"DECODEX_PYTHON": str(fake_python)})
        self.assertEqual(Path(resolved), fake_python)

    def test_search_finds_skill_by_id_title_and_tag(self) -> None:
        by_id = search_repository(self.root, "safe-runtime-modification")
        by_title = search_repository(self.root, "Safe Runtime Modification")
        by_tag = search_repository(self.root, "runtime")

        self.assertTrue(any("safe-runtime-modification" in str(path) for path in by_id))
        self.assertTrue(any("safe-runtime-modification" in str(path) for path in by_title))
        self.assertTrue(any("safe-runtime-modification" in str(path) for path in by_tag))

    def test_capture_stays_within_workspace(self) -> None:
        session_dir = capture_session(
            self.root,
            project="decodex",
            session_id="contract-check",
            goal="Validate workspace safety",
            session_date="2026-06-20",
        )
        self.assertTrue(session_dir.resolve().is_relative_to(self.root.resolve()))
        self.assertTrue((session_dir / "session.yaml").exists())

    def test_init_workspace_creates_valid_skeleton(self) -> None:
        target = Path(self._tmp.name) / "fresh-decodex"
        created = init_workspace(target)
        self.assertTrue((target / "decodex.yaml").exists())
        self.assertTrue((target / "registry" / "skills-index.yaml").exists())
        self.assertGreater(len(created), 0)
        self.assertEqual(validate_repository(target), [])
        self.assertEqual(audit_repository(target), [])

    def test_audit_detects_broken_index(self) -> None:
        broken_index = self.root / "registry" / "skills-index.yaml"
        data = load_jsonish(broken_index)
        data["skills"][0]["path"] = "global/skills/missing-skill/skill.yaml"
        broken_index.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        errors = audit_repository(self.root)
        self.assertTrue(any("missing indexed skill file" in error for error in errors))

    def test_audit_detects_absolute_windows_path(self) -> None:
        rogue = self.root / "notes.md"
        rogue.write_text("C" + ":" + "\\" + "temp" + "\\" + "oops" + "\\" + "file.txt", encoding="utf-8")
        errors = audit_repository(self.root)
        self.assertTrue(any("absolute Windows path" in error for error in errors))

    def test_init_project_registers_project(self) -> None:
        target = Path(self._tmp.name) / "fresh-decodex"
        init_workspace(target)
        created = init_project(target, "pac-hunt-2", source=self.root)
        self.assertTrue((target / "projects" / "pac-hunt-2" / "project.yaml").exists())
        self.assertTrue((target / "registry" / "projects-index.yaml").exists())
        self.assertGreater(len(created), 0)
        self.assertEqual(validate_repository(target), [])

    def test_context_check_detects_stale_context(self) -> None:
        context_file = self.root / ".codex" / "project-context.md"
        context_file.write_text(context_file.read_text(encoding="utf-8") + "\n- tampered\n", encoding="utf-8")
        errors = context_check(self.root, project="decodex")
        self.assertTrue(any("context diverges" in error or "stale" in error for error in errors))

    def test_session_close_writes_compliance_report_and_feedback(self) -> None:
        report = session_close(
            self.root,
            project="decodex",
            session="2026-06-20-v0.1.3-self-improving-development-loop",
            tests=[
                "python -m unittest discover -s tests -v",
                "python tools\\decodex.py validate --root .",
                "python tools\\decodex.py audit --root .",
            ],
            lessons=[
                "Decodex can now verify and initialize its own memory.",
            ],
            artifacts=[
                "README.md",
                "decodex.yaml",
            ],
            useful_rules=[
                "validate before audit",
                "refuse writes outside workspace",
            ],
            missing_rules=[
                "require a clean Git worktree before schema migration",
            ],
            ambiguous_rules=[
                "preserve provenance for generated files",
            ],
            skill_candidates=[
                "context-compliance-review",
            ],
        )
        self.assertTrue(report.exists())
        session_dir = report.parent
        self.assertTrue((session_dir / "feedback.yaml").exists())
        self.assertTrue((session_dir / "session.yaml").exists())
        self.assertTrue((self.root / "projects" / "decodex" / "skills" / "context-compliance-review" / "skill.yaml").exists())


if __name__ == "__main__":
    unittest.main()

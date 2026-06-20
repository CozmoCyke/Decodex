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
    DecodexError,
    capture_session,
    load_jsonish,
    resolve_python_interpreter,
    search_repository,
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

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_repository_contract_validates(self) -> None:
        self.assertEqual(validate_repository(self.root), [])

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


if __name__ == "__main__":
    unittest.main()

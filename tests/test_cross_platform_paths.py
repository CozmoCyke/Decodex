from __future__ import annotations

import ctypes
import shutil
import tempfile
import unittest
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from decodex_core import DecodexError, _list_skill_records, _workspace_relative_path, build_context


def windows_short_path(path: Path) -> Path:
    buffer = ctypes.create_unicode_buffer(32768)
    result = ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, len(buffer))
    if result == 0:
        raise OSError("GetShortPathNameW failed")
    return Path(buffer.value)


class CrossPlatformPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name) / "Decodex"
        shutil.copytree(
            ROOT,
            self.repo,
            ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"),
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_workspace_relative_path_returns_posix(self) -> None:
        artifact = (
            self.repo
            / "projects"
            / "decodex"
            / "skills"
            / "context-compliance-review"
            / "evaluations"
            / "source-eval"
            / "evaluation.yaml"
        )
        relative = _workspace_relative_path(self.repo, artifact)
        self.assertEqual(
            relative,
            "projects/decodex/skills/context-compliance-review/evaluations/source-eval/evaluation.yaml",
        )

    def test_workspace_relative_path_rejects_external_path(self) -> None:
        external = Path(self._tmp.name).parent / "outside.yaml"
        with self.assertRaises(DecodexError):
            _workspace_relative_path(self.repo, external)

    def test_build_context_from_temporary_copy(self) -> None:
        context_dir = build_context(self.repo, project="decodex", output_root=self.repo)
        self.assertTrue((context_dir / "provenance.json").exists())
        self.assertTrue((context_dir / "project-context.md").exists())

    def test_list_skill_records_has_canonical_paths(self) -> None:
        build_context(self.repo, project="decodex", output_root=self.repo)
        records = _list_skill_records(self.repo, self.repo / "projects" / "decodex" / "skills")
        self.assertTrue(records)
        record = next(item for item in records if item["id"] == "context-compliance-review")
        self.assertIn("/", record["source_path"])
        self.assertIsNotNone(record["latest_evaluation"])
        self.assertIsNotNone(record["latest_review"])
        self.assertIsNotNone(record["latest_approval"])
        self.assertIn("/", record["latest_evaluation"]["path"])
        self.assertIn("/", record["latest_review"]["path"])
        self.assertIn("/", record["latest_approval"]["path"])

    @unittest.skipUnless(sys.platform.startswith("win"), "Windows-specific path alias test")
    def test_short_and_long_windows_paths_share_workspace(self) -> None:
        try:
            short_root = windows_short_path(self.repo.resolve())
        except OSError:
            self.skipTest("GetShortPathNameW returned no alias on this machine")

        artifact = (
            self.repo.resolve()
            / "projects"
            / "decodex"
            / "skills"
            / "context-compliance-review"
            / "evaluations"
            / "source-eval"
            / "evaluation.yaml"
        )

        relative = _workspace_relative_path(short_root, artifact)
        self.assertEqual(
            relative,
            "projects/decodex/skills/context-compliance-review/evaluations/source-eval/evaluation.yaml",
        )


if __name__ == "__main__":
    unittest.main()

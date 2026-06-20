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

from decodex_core import build_context, capture_session, context_check, load_jsonish, promote_skill, search_repository


class GoldenPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "Decodex"
        shutil.copytree(
            ROOT,
            self.root,
            ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"),
        )
        shutil.rmtree(self.root / "global" / "skills" / "static-dynamic-render-split")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_pachunt_golden_path(self) -> None:
        session_fixture = load_jsonish(
            self.root / "projects" / "pac-hunt-2" / "sessions" / "2026-06-20-performance" / "session.yaml"
        )

        session_dir = capture_session(
            self.root,
            project=session_fixture["project"],
            session_id=session_fixture["id"],
            goal=session_fixture["goal"],
            session_date=session_fixture["date"],
            lessons=session_fixture["lessons"]["project"],
            global_candidates=session_fixture["lessons"]["global_candidates"],
        )

        self.assertTrue((session_dir / "session.yaml").exists())

        source_dir, target_dir = promote_skill(
            self.root,
            skill_id="static-dynamic-render-split",
            from_scope="project",
            to_scope="global",
            project="pac-hunt-2",
        )
        self.assertTrue(source_dir.exists())
        self.assertTrue(target_dir.exists())

        history_lines = (self.root / "registry" / "promotion-history.jsonl").read_text(encoding="utf-8").strip().splitlines()
        last_event = json.loads(history_lines[-1])
        self.assertEqual(last_event["skill_id"], "static-dynamic-render-split")
        self.assertEqual(last_event["from"], "project")
        self.assertEqual(last_event["to"], "global")
        self.assertEqual(last_event["project"], "pac-hunt-2")

        matches = search_repository(self.root, "static-dynamic-render-split")
        self.assertTrue(
            any("projects/pac-hunt-2/skills/static-dynamic-render-split" in path.as_posix() for path in matches)
        )
        self.assertTrue(any("global/skills/static-dynamic-render-split" in path.as_posix() for path in matches))

        output_root = self.root / "generated"
        context_dir = build_context(self.root, project="pac-hunt-2", output_root=output_root)
        self.assertTrue((context_dir / "AGENTS.md").exists())
        self.assertTrue((context_dir / "project-context.md").exists())
        self.assertTrue((context_dir / "safety-checklist.md").exists())
        self.assertTrue((context_dir / "testing-strategy.md").exists())
        self.assertTrue((context_dir / "inherited-skills.md").exists())
        self.assertTrue((context_dir / "provenance.json").exists())

        inherited = (context_dir / "inherited-skills.md").read_text(encoding="utf-8")
        self.assertIn("origin_project=pac-hunt-2", inherited)
        provenance = json.loads((context_dir / "provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(provenance["project"], "pac-hunt-2")
        self.assertTrue(any(item["id"] == "static-dynamic-render-split" for item in provenance["inherited_skills"]))
        self.assertEqual(context_check(self.root, project="pac-hunt-2", context_root=self.root / "generated"), [])


if __name__ == "__main__":
    unittest.main()

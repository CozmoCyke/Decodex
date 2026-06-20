"""Core helpers for Decodex validation, search, capture, and promotion."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


class DecodexError(RuntimeError):
    """Raised when Decodex validation or operations fail."""

    def __init__(self, message: str, *, code: int = 1):
        super().__init__(message)
        self.code = code


def _duplicate_key_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for key, value in pairs:
        if key in data:
            raise DecodexError(f"duplicate key: {key}")
        data[key] = value
    return data


def load_jsonish(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise DecodexError(f"missing file: {path}") from exc
    try:
        return json.loads(text, object_pairs_hook=_duplicate_key_hook)
    except json.JSONDecodeError as exc:
        location = f"{path}:{exc.lineno}:{exc.colno}"
        raise DecodexError(f"invalid YAML/JSON at {location}: {exc.msg}") from exc


def dump_jsonish(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def ensure_within_root(root: Path, target: Path) -> Path:
    root = root.resolve()
    target = target.resolve()
    if target == root or root in target.parents:
        return target
    raise DecodexError(f"refusing to write outside workspace: {target}")


def validate_schema(instance: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    errors: list[str] = []
    expected_type = schema.get("type")

    def fail(message: str) -> None:
        errors.append(f"{path}: {message}")

    if expected_type == "object":
        if not isinstance(instance, dict):
            fail(f"expected object, got {type(instance).__name__}")
            return errors
        required = schema.get("required", [])
        for key in required:
            if key not in instance:
                errors.append(f"{path}: missing required property {key!r}")
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        for key, value in instance.items():
            if key in properties:
                errors.extend(validate_schema(value, properties[key], f"{path}.{key}"))
            elif additional is False:
                errors.append(f"{path}: unexpected property {key!r}")
        return errors

    if expected_type == "array":
        if not isinstance(instance, list):
            fail(f"expected array, got {type(instance).__name__}")
            return errors
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(instance):
                errors.extend(validate_schema(item, item_schema, f"{path}[{index}]"))
        return errors

    if expected_type == "string":
        if not isinstance(instance, str):
            fail(f"expected string, got {type(instance).__name__}")
        else:
            enum_values = schema.get("enum")
            if enum_values and instance not in enum_values:
                fail(f"expected one of {enum_values!r}")
        return errors

    if expected_type == "integer":
        if not isinstance(instance, int) or isinstance(instance, bool):
            fail(f"expected integer, got {type(instance).__name__}")
        return errors

    if expected_type == "number":
        if not isinstance(instance, (int, float)) or isinstance(instance, bool):
            fail(f"expected number, got {type(instance).__name__}")
        return errors

    if expected_type == "boolean":
        if not isinstance(instance, bool):
            fail(f"expected boolean, got {type(instance).__name__}")
        return errors

    enum_values = schema.get("enum")
    if enum_values and instance not in enum_values:
        fail(f"expected one of {enum_values!r}")
    return errors


def validate_json_schema_file(instance_path: Path, schema_path: Path) -> list[str]:
    instance = load_jsonish(instance_path)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return validate_schema(instance, schema)


def default_root() -> Path:
    return Path(__file__).resolve().parent


def load_manifest(root: Path) -> dict[str, Any]:
    return load_jsonish(root / "decodex.yaml")


def resolve_python_interpreter(root: Path, env: os._Environ[str] | dict[str, str] | None = None) -> str:
    env = env or os.environ
    manifest = load_manifest(root)
    runtime = manifest.get("runtime", {})
    candidates: list[str] = []

    configured = runtime.get("python_executable")
    if isinstance(configured, str) and configured:
        candidates.append(configured)

    env_configured = env.get("DECODEX_PYTHON")
    if env_configured:
        candidates.append(env_configured)

    env_python = env.get("PYTHON")
    if env_python:
        candidates.append(env_python)

    env_python3 = env.get("PYTHON3")
    if env_python3:
        candidates.append(env_python3)

    candidate_list = runtime.get("python_candidates", ["python", "python3"])
    if isinstance(candidate_list, list):
        candidates.extend(str(candidate) for candidate in candidate_list if candidate)

    seen: set[str] = set()
    for candidate in candidates:
        normalized = candidate.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        candidate_path = Path(normalized)
        if candidate_path.is_absolute():
            if candidate_path.exists():
                return str(candidate_path)
            continue
        resolved = shutil.which(normalized)
        if resolved:
            return resolved

    raise DecodexError("no usable Python interpreter found")


def _load_schema(root: Path, name: str) -> dict[str, Any]:
    return json.loads((root / "schemas" / name).read_text(encoding="utf-8"))


def validate_repository(root: Path) -> list[str]:
    errors: list[str] = []

    manifest_path = root / "decodex.yaml"
    manifest = load_jsonish(manifest_path)
    errors.extend(validate_schema(manifest, _load_schema(root, "decodex.schema.json")))

    for schema_name, relative_path in [
        ("project.schema.json", Path("projects/decodex/project.yaml")),
        ("project.schema.json", Path("projects/pac-hunt-2/project.yaml")),
        ("skill.schema.json", Path("global/skills/safe-runtime-modification/skill.yaml")),
        ("skill.schema.json", Path("projects/pac-hunt-2/skills/static-dynamic-render-split/skill.yaml")),
    ]:
        file_path = root / relative_path
        if file_path.exists():
            try:
                errors.extend(validate_json_schema_file(file_path, root / "schemas" / schema_name))
            except DecodexError as exc:
                errors.append(str(exc))

    for index_path, key in [
        (root / "registry" / "skills-index.yaml", "skills"),
        (root / "registry" / "projects-index.yaml", "projects"),
    ]:
        if index_path.exists():
            try:
                data = load_jsonish(index_path)
                if key not in data or not isinstance(data[key], list):
                    errors.append(f"{index_path}: expected top-level list under {key!r}")
            except DecodexError as exc:
                errors.append(str(exc))

    for skill_path in _discover_skill_files(root):
        try:
            errors.extend(validate_json_schema_file(skill_path, root / "schemas" / "skill.schema.json"))
        except DecodexError as exc:
            errors.append(str(exc))

    return errors


def _discover_skill_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for base in [root / "global" / "skills", root / "projects"]:
        if not base.exists():
            continue
        for path in base.rglob("skill.yaml"):
            files.append(path)
    return sorted({path.resolve() for path in files})


def search_repository(root: Path, query: str) -> list[Path]:
    needle = query.casefold()
    matches: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".md", ".yaml", ".yml", ".json", ".jsonl", ".txt"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if needle in path.as_posix().casefold() or needle in text.casefold():
            matches.append(path)
            continue
        if path.suffix.lower() in {".yaml", ".yml", ".json", ".jsonl"}:
            try:
                data = load_jsonish(path)
            except DecodexError:
                continue
            if _contains_value(data, needle):
                matches.append(path)
    return sorted({path.resolve() for path in matches})


def _contains_value(value: Any, needle: str) -> bool:
    if isinstance(value, str):
        return needle in value.casefold()
    if isinstance(value, dict):
        return any(_contains_value(v, needle) or needle in str(k).casefold() for k, v in value.items())
    if isinstance(value, list):
        return any(_contains_value(item, needle) for item in value)
    if isinstance(value, (int, float, bool)) or value is None:
        return needle in str(value).casefold()
    return False


def capture_session(
    root: Path,
    *,
    project: str,
    session_id: str,
    goal: str,
    session_date: str,
    lessons: list[str] | None = None,
    global_candidates: list[str] | None = None,
) -> Path:
    session_dir = ensure_within_root(root, root / "inbox" / "sessions" / session_id)
    session_dir.mkdir(parents=True, exist_ok=False)
    session_data = {
        "id": session_id,
        "project": project,
        "date": session_date,
        "goal": goal,
        "lessons": lessons or [],
        "global_candidates": global_candidates or [],
    }
    dump_jsonish(session_dir / "session.yaml", session_data)
    return session_dir


def promote_skill(
    root: Path,
    *,
    skill_id: str,
    from_scope: str,
    to_scope: str,
    project: str | None = None,
    force: bool = False,
) -> tuple[Path, Path]:
    source_dir = _skill_dir(root, skill_id, from_scope, project=project)
    target_dir = _skill_dir(root, skill_id, to_scope, project=project)

    if not source_dir.exists():
        raise DecodexError(f"source skill not found: {source_dir}")
    if target_dir.exists():
        if not force:
            raise DecodexError(f"target skill already exists: {target_dir}")
        shutil.rmtree(target_dir)

    target_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_dir, target_dir)

    history = root / "registry" / "promotion-history.jsonl"
    history.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "skill_id": skill_id,
        "from": from_scope,
        "to": to_scope,
        "project": project,
        "source_path": str(source_dir.relative_to(root)),
        "target_path": str(target_dir.relative_to(root)),
    }
    with history.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=True) + "\n")
    return source_dir, target_dir


def _skill_dir(root: Path, skill_id: str, scope: str, *, project: str | None) -> Path:
    if scope == "global":
        return root / "global" / "skills" / skill_id
    if scope == "project":
        if not project:
            raise DecodexError("project is required when scope is project")
        return root / "projects" / project / "skills" / skill_id
    raise DecodexError(f"unknown scope: {scope}")


def build_context(root: Path, *, project: str, output_root: Path) -> Path:
    workspace_output = ensure_within_root(root, output_root)
    context_dir = ensure_within_root(root, workspace_output / ".codex")
    context_dir.mkdir(parents=True, exist_ok=True)

    project_skill_ids = _list_skill_ids(root / "projects" / project / "skills")
    global_skill_ids = _list_skill_ids(root / "global" / "skills")

    files = {
        "AGENTS.md": "# Agent Context\n\nGenerated by Decodex.\n",
        "project-skill.md": _render_skill_list("Project Skills", project_skill_ids),
        "safety-checklist.md": "# Safety Checklist\n\n- Snapshot\n- Validation\n- Rollback\n",
        "testing-strategy.md": "# Testing Strategy\n\n- Syntax\n- Functional\n- Regression\n",
        "inherited-skills.md": _render_skill_list("Inherited Skills", global_skill_ids),
    }
    for filename, content in files.items():
        (context_dir / filename).write_text(content, encoding="utf-8")
    return context_dir


def _render_skill_list(title: str, skills: Iterable[str]) -> str:
    lines = [f"# {title}", ""]
    for skill in skills:
        lines.append(f"- {skill}")
    if len(lines) == 2:
        lines.append("- None")
    lines.append("")
    return "\n".join(lines)


def _list_skill_ids(base: Path) -> list[str]:
    if not base.exists():
        return []
    ids: list[str] = []
    for skill_file in sorted(base.rglob("skill.yaml")):
        try:
            skill = load_jsonish(skill_file)
        except DecodexError:
            continue
        skill_id = skill.get("id")
        title = skill.get("title", skill_id)
        if isinstance(skill_id, str):
            ids.append(f"{skill_id} - {title}")
    return ids

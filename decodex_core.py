"""Core helpers for Decodex validation, audit, search, capture, promotion, and init."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
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


def write_template_text(path: Path, content: str, *, force: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if existing == content:
            return
        if not force:
            raise DecodexError(f"refusing to overwrite existing file: {path}")
    path.write_text(content, encoding="utf-8")


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
    if manifest_path.exists():
        try:
            manifest = load_jsonish(manifest_path)
            errors.extend(validate_schema(manifest, _load_schema(root, "decodex.schema.json")))
        except DecodexError as exc:
            errors.append(str(exc))
    else:
        errors.append(f"missing file: {manifest_path}")

    for project_path in _discover_project_files(root):
        try:
            errors.extend(validate_json_schema_file(project_path, root / "schemas" / "project.schema.json"))
        except DecodexError as exc:
            errors.append(str(exc))

    for session_path in _discover_session_files(root):
        try:
            errors.extend(validate_json_schema_file(session_path, root / "schemas" / "session.schema.json"))
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


def audit_repository(root: Path) -> list[str]:
    errors = validate_repository(root)
    errors.extend(_audit_schema_compatibility(root))
    errors.extend(_audit_indexes(root))
    errors.extend(_audit_duplicate_skill_ids(root))
    errors.extend(_audit_project_structure(root))
    errors.extend(_audit_sessions(root))
    errors.extend(_audit_promotions(root))
    errors.extend(_audit_absolute_paths(root))
    errors.extend(_audit_tracked_generated_files(root))
    errors.extend(_audit_evidence_references(root))
    return sorted(dict.fromkeys(errors))


def _discover_skill_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for base in [root / "global" / "skills", root / "projects"]:
        if not base.exists():
            continue
        for path in base.rglob("skill.yaml"):
            files.append(path)
    return sorted({path.resolve() for path in files})


def _discover_project_files(root: Path) -> list[Path]:
    files: list[Path] = []
    projects_dir = root / "projects"
    if not projects_dir.exists():
        return []
    for path in projects_dir.rglob("project.yaml"):
        files.append(path)
    return sorted({path.resolve() for path in files})


def _discover_session_files(root: Path) -> list[Path]:
    files: list[Path] = []
    projects_dir = root / "projects"
    if not projects_dir.exists():
        return []
    for path in projects_dir.rglob("session.yaml"):
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

    project_skills = _list_skill_records(root, root / "projects" / project / "skills")
    inherited_skills = _list_skill_records(root, root / "global" / "skills")

    files = {
        "AGENTS.md": "# Agent Context\n\nGenerated by Decodex.\n",
        "project-context.md": _render_project_context(project, project_skills),
        "safety-checklist.md": "# Safety Checklist\n\n- Snapshot\n- Validation\n- Rollback\n",
        "testing-strategy.md": "# Testing Strategy\n\n- Syntax\n- Functional\n- Regression\n",
        "inherited-skills.md": _render_inherited_skills(inherited_skills),
        "provenance.json": json.dumps(
            {
                "project": project,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "project_skills": project_skills,
                "inherited_skills": inherited_skills,
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n",
    }
    for filename, content in files.items():
        write_template_text(context_dir / filename, content, force=True)
    return context_dir


def _render_project_context(project: str, skills: list[dict[str, Any]]) -> str:
    lines = [f"# Project Context", "", f"- Project: {project}", ""]
    if not skills:
        lines.append("- No project skills recorded yet.")
    else:
        lines.append("## Project Skills")
        for skill in skills:
            lines.append(f"- {skill['id']} - {skill.get('title', skill['id'])}")
    lines.append("")
    return "\n".join(lines)


def _render_inherited_skills(skills: list[dict[str, Any]]) -> str:
    lines = ["# Inherited Skills", ""]
    if not skills:
        lines.append("- None")
    else:
        for skill in skills:
            evidence = ", ".join(skill.get("evidence", [])) or "none"
            lines.append(
                f"- {skill['id']} | scope={skill.get('scope', 'global')} | "
                f"origin_project={skill.get('origin_project', 'unknown')} | "
                f"confidence={skill.get('confidence', 'unknown')} | evidence={evidence}"
            )
    lines.append("")
    return "\n".join(lines)


def _list_skill_records(root: Path, base: Path) -> list[dict[str, Any]]:
    if not base.exists():
        return []
    records: list[dict[str, Any]] = []
    for skill_file in sorted(base.rglob("skill.yaml")):
        try:
            skill = load_jsonish(skill_file)
        except DecodexError:
            continue
        skill_id = skill.get("id")
        if isinstance(skill_id, str):
            record = {
                "id": skill_id,
                "title": skill.get("title", skill_id),
                "scope": skill.get("scope", "unknown"),
                "origin_project": skill.get("origin_project") or _infer_origin_project(skill_file),
                "confidence": skill.get("confidence", "unknown"),
                "evidence": skill.get("evidence", []),
                "source_path": skill_file.relative_to(root).as_posix(),
            }
            records.append(record)
    return records


def _infer_origin_project(skill_file: Path) -> str:
    parts = skill_file.parts
    if "projects" in parts:
        index = parts.index("projects")
        if index + 1 < len(parts):
            return parts[index + 1]
    return "unknown"


def _audit_schema_compatibility(root: Path) -> list[str]:
    errors: list[str] = []
    manifest_path = root / "decodex.yaml"
    schema_path = root / "schemas" / "decodex.schema.json"
    if not manifest_path.exists() or not schema_path.exists():
        return errors
    try:
        manifest = load_jsonish(manifest_path)
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except DecodexError as exc:
        return [str(exc)]
    except json.JSONDecodeError as exc:
        return [f"{schema_path}: invalid JSON: {exc.msg}"]

    expected = schema.get("x-decodex-version")
    actual = manifest.get("version")
    if expected and actual != expected:
        errors.append(f"{manifest_path}: version {actual!r} is incompatible with schema {expected!r}")
    return errors


def _audit_indexes(root: Path) -> list[str]:
    errors: list[str] = []
    skill_index_path = root / "registry" / "skills-index.yaml"
    project_index_path = root / "registry" / "projects-index.yaml"

    if skill_index_path.exists():
        try:
            data = load_jsonish(skill_index_path)
        except DecodexError as exc:
            return [str(exc)]
        skills = data.get("skills", [])
        seen_ids: set[str] = set()
        for entry in skills if isinstance(skills, list) else []:
            if not isinstance(entry, dict):
                errors.append(f"{skill_index_path}: skill entries must be objects")
                continue
            skill_id = entry.get("id")
            path_value = entry.get("path")
            if not isinstance(skill_id, str) or not skill_id:
                errors.append(f"{skill_index_path}: skill entry missing id")
            if not isinstance(path_value, str) or not path_value:
                errors.append(f"{skill_index_path}: skill entry {skill_id!r} missing path")
            elif not (root / path_value).exists():
                errors.append(f"{skill_index_path}: missing indexed skill file {path_value}")
            if isinstance(skill_id, str):
                if skill_id in seen_ids:
                    errors.append(f"{skill_index_path}: duplicate skill id {skill_id}")
                seen_ids.add(skill_id)
    if project_index_path.exists():
        try:
            data = load_jsonish(project_index_path)
        except DecodexError as exc:
            return errors + [str(exc)]
        projects = data.get("projects", [])
        seen_ids: set[str] = set()
        for entry in projects if isinstance(projects, list) else []:
            if not isinstance(entry, dict):
                errors.append(f"{project_index_path}: project entries must be objects")
                continue
            project_id = entry.get("id")
            path_value = entry.get("path")
            if not isinstance(project_id, str) or not project_id:
                errors.append(f"{project_index_path}: project entry missing id")
            if not isinstance(path_value, str) or not path_value:
                errors.append(f"{project_index_path}: project entry {project_id!r} missing path")
            elif not (root / path_value).exists():
                errors.append(f"{project_index_path}: missing indexed project file {path_value}")
            if isinstance(project_id, str):
                if project_id in seen_ids:
                    errors.append(f"{project_index_path}: duplicate project id {project_id}")
                seen_ids.add(project_id)
    return errors


def _audit_duplicate_skill_ids(root: Path) -> list[str]:
    errors: list[str] = []
    seen: dict[str, list[Path]] = {}
    for skill_file in _discover_skill_files(root):
        try:
            skill = load_jsonish(skill_file)
        except DecodexError as exc:
            errors.append(str(exc))
            continue
        skill_id = skill.get("id")
        if isinstance(skill_id, str):
            seen.setdefault(skill_id, []).append(skill_file)

    for skill_id, files in seen.items():
        if len(files) <= 1:
            continue
        scopes = {_skill_scope_for_path(root, file) for file in files}
        if scopes == {"project", "global"} and len(files) == 2 and _has_matching_promotion_event(root, skill_id, files):
            continue
        errors.append(f"duplicate skill id {skill_id}: " + ", ".join(str(path) for path in files))
    return errors


def _skill_scope_for_path(root: Path, path: Path) -> str:
    relative = path.relative_to(root).parts
    if relative[:2] == ("global", "skills"):
        return "global"
    if relative[:1] == ("projects",):
        return "project"
    return "unknown"


def _has_matching_promotion_event(root: Path, skill_id: str, files: list[Path]) -> bool:
    history = root / "registry" / "promotion-history.jsonl"
    if not history.exists():
        return False
    project_file = next((path for path in files if _skill_scope_for_path(root, path) == "project"), None)
    global_file = next((path for path in files if _skill_scope_for_path(root, path) == "global"), None)
    if project_file is None or global_file is None:
        return False
    source_path = project_file.relative_to(root).parent.as_posix()
    target_path = global_file.relative_to(root).parent.as_posix()
    for line in history.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("skill_id") != skill_id:
            continue
        if event.get("source_path") == source_path and event.get("target_path") == target_path:
            return True
    return False


def _audit_project_structure(root: Path) -> list[str]:
    errors: list[str] = []
    projects_dir = root / "projects"
    if not projects_dir.exists():
        return errors
    for project_dir in [p for p in projects_dir.iterdir() if p.is_dir()]:
        project_file = project_dir / "project.yaml"
        if not project_file.exists():
            errors.append(f"missing project.yaml: {project_file}")
    return errors


def _audit_sessions(root: Path) -> list[str]:
    errors: list[str] = []
    projects = _project_ids(root)
    for session_file in _discover_session_files(root):
        try:
            session = load_jsonish(session_file)
        except DecodexError as exc:
            errors.append(str(exc))
            continue
        project = session.get("project")
        if not isinstance(project, str) or project not in projects:
            errors.append(f"{session_file}: invalid project reference {project!r}")
        parent_project = session_file.parent.parent.parent.name
        if isinstance(project, str) and project != parent_project:
            errors.append(f"{session_file}: session project {project!r} does not match parent project {parent_project!r}")
    return errors


def _audit_promotions(root: Path) -> list[str]:
    errors: list[str] = []
    history = root / "registry" / "promotion-history.jsonl"
    if not history.exists():
        return errors
    for line_no, line in enumerate(history.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{history}:{line_no}: invalid JSON: {exc.msg}")
            continue
        source_path = event.get("source_path")
        target_path = event.get("target_path")
        if not isinstance(source_path, str) or not source_path:
            errors.append(f"{history}:{line_no}: missing provenance source_path")
        elif not (root / source_path).exists():
            errors.append(f"{history}:{line_no}: missing provenance source file {source_path}")
        if not isinstance(target_path, str) or not target_path:
            errors.append(f"{history}:{line_no}: missing provenance target_path")
    return errors


_WINDOWS_ABSOLUTE_PATH = re.compile(r"[A-Za-z]:\\")


def _audit_absolute_paths(root: Path) -> list[str]:
    errors: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".md", ".yaml", ".yml", ".json", ".jsonl", ".txt", ".ps1", ".cmd"}:
            continue
        if path.suffix.lower() == ".py":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if _WINDOWS_ABSOLUTE_PATH.search(text):
            errors.append(f"{path}: contains an absolute Windows path")
    return errors


def _audit_tracked_generated_files(root: Path) -> list[str]:
    patterns = ["__pycache__", ".pytest_cache", ".coverage", "htmlcov", ".venv", "venv", ".env", "*.tmp", "*.log"]
    errors: list[str] = []
    try:
        result = subprocess.run(
            ["git", "-c", f"safe.directory={root.as_posix()}", "ls-files"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return errors
    if result.returncode != 0:
        return errors
    tracked = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    for path in tracked:
        for pattern in patterns:
            if pattern in {"__pycache__", ".pytest_cache", ".coverage", "htmlcov", ".venv", "venv", ".env"}:
                if pattern in path:
                    errors.append(f"tracked generated file: {path}")
                    break
            elif pattern == "*.tmp" and path.endswith(".tmp"):
                errors.append(f"tracked generated file: {path}")
                break
            elif pattern == "*.log" and path.endswith(".log"):
                errors.append(f"tracked generated file: {path}")
                break
    return errors


def _audit_evidence_references(root: Path) -> list[str]:
    errors: list[str] = []
    for skill_file in _discover_skill_files(root):
        try:
            skill = load_jsonish(skill_file)
        except DecodexError as exc:
            errors.append(str(exc))
            continue
        evidence = skill.get("evidence", [])
        if isinstance(evidence, list):
            for entry in evidence:
                if isinstance(entry, str) and entry and not (root / entry).exists():
                    errors.append(f"{skill_file}: missing evidence file {entry}")
    return errors


def _project_ids(root: Path) -> set[str]:
    ids: set[str] = set()
    for project_file in _discover_project_files(root):
        try:
            project = load_jsonish(project_file)
        except DecodexError:
            continue
        project_id = project.get("id")
        if isinstance(project_id, str):
            ids.add(project_id)
    return ids


def init_workspace(root: Path, *, force: bool = False) -> list[Path]:
    created: list[Path] = []
    root.mkdir(parents=True, exist_ok=True)

    text_templates = {
        "README.md": "# Decodex\n\nLocal memory system for development work.\n",
        ".gitignore": "__pycache__/\n*.py[cod]\n.pytest_cache/\n.coverage\nhtmlcov/\n.venv/\nvenv/\n.env\n*.tmp\n*.log\n",
        "inbox/README.md": "# Inbox\n\nRaw capture area for sessions and evidence.\n",
        "global/README.md": "# Global\n\nReusable skills, patterns, and checklists.\n",
        "projects/README.md": "# Projects\n\nProject-specific memory lives here.\n",
        "tools/README.md": "# Tools\n\nUtility scripts for capture, search, promotion, init, and context generation.\n",
    }
    json_templates = {
        "decodex.yaml": {
            "name": "Decodex",
            "version": "0.1.2",
            "status": "mvp",
            "runtime": {"python_candidates": ["python", "python3"]},
            "layers": {
                "inbox": {"purpose": "raw session evidence"},
                "projects": {"purpose": "validated project-specific knowledge"},
                "global": {"purpose": "cross-project reusable knowledge"},
            },
            "registry": {
                "skills_index": "registry/skills-index.yaml",
                "projects_index": "registry/projects-index.yaml",
                "promotion_history": "registry/promotion-history.jsonl",
            },
            "conventions": {
                "knowledge_states": [
                    "RAW",
                    "OBSERVED",
                    "CANDIDATE",
                    "PROJECT_VALIDATED",
                    "GLOBAL_VALIDATED",
                    "DEPRECATED",
                ]
            },
        },
        "registry/skills-index.yaml": {"skills": []},
        "registry/projects-index.yaml": {"projects": []},
        "schemas/decodex.schema.json": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "Decodex Manifest",
            "x-decodex-version": "0.1.2",
            "type": "object",
            "required": ["name", "version", "status", "runtime", "layers", "registry", "conventions"],
            "properties": {
                "name": {"type": "string"},
                "version": {"type": "string"},
                "status": {"type": "string"},
                "runtime": {"type": "object"},
                "layers": {"type": "object"},
                "registry": {"type": "object"},
                "conventions": {"type": "object"},
            },
            "additionalProperties": True,
        },
        "schemas/project.schema.json": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "Decodex Project",
            "x-decodex-version": "0.1.2",
            "type": "object",
            "required": ["id", "name", "status", "domains"],
            "properties": {
                "id": {"type": "string"},
                "name": {"type": "string"},
                "status": {"type": "string"},
                "domains": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": True,
        },
        "schemas/session.schema.json": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "Decodex Session",
            "x-decodex-version": "0.1.2",
            "type": "object",
            "required": ["id", "project", "date", "goal"],
            "properties": {
                "id": {"type": "string"},
                "project": {"type": "string"},
                "date": {"type": "string"},
                "goal": {"type": "string"},
            },
            "additionalProperties": True,
        },
        "schemas/skill.schema.json": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "Decodex Skill",
            "x-decodex-version": "0.1.2",
            "type": "object",
            "required": ["id", "title", "version", "status", "scope"],
            "properties": {
                "id": {"type": "string"},
                "title": {"type": "string"},
                "version": {"type": "string"},
                "status": {"type": "string"},
                "scope": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "evidence": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": True,
        },
        "schemas/decision.schema.json": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "Decodex Decision",
            "x-decodex-version": "0.1.2",
            "type": "object",
            "required": ["id", "project", "summary", "status"],
            "properties": {
                "id": {"type": "string"},
                "project": {"type": "string"},
                "summary": {"type": "string"},
                "status": {"type": "string"},
            },
            "additionalProperties": True,
        },
    }
    text_templates["registry/promotion-history.jsonl"] = ""
    for rel, text in text_templates.items():
        path = root / rel
        write_template_text(path, text, force=force)
        created.append(path)
    for rel, data in json_templates.items():
        path = root / rel
        dump_jsonish(path, data)
        created.append(path)

    validate_errors = validate_repository(root)
    if validate_errors:
        raise DecodexError("initialization produced an invalid repository:\n" + "\n".join(validate_errors))
    return created


def init_project(root: Path, project: str, *, source: Path | None = None, force: bool = False) -> list[Path]:
    created: list[Path] = []
    project_root = root / "projects" / project
    project_root.mkdir(parents=True, exist_ok=True)
    project_data = {
        "id": project,
        "name": project.replace("-", " ").title(),
        "status": "active",
        "domains": ["workflow"],
    }
    if source is not None:
        project_data["source_root"] = str(source)

    write_template_text(project_root / "README.md", f"# {project}\n\nProject memory for {project}.\n", force=force)
    dump_jsonish(project_root / "project.yaml", project_data)
    created.append(project_root / "project.yaml")

    for rel in [
        "sessions/README.md",
        "skills/README.md",
        "decisions/README.md",
        "incidents/README.md",
        "checkpoints/README.md",
        "reports/README.md",
    ]:
        path = project_root / rel
        write_template_text(path, f"# {path.parent.name.title()}\n\n", force=force)
        created.append(path)

    projects_index_path = root / "registry" / "projects-index.yaml"
    if projects_index_path.exists():
        index = load_jsonish(projects_index_path)
    else:
        index = {"projects": []}
    projects = index.setdefault("projects", [])
    if not isinstance(projects, list):
        raise DecodexError(f"{projects_index_path}: projects index must contain a list")
    existing = next((entry for entry in projects if isinstance(entry, dict) and entry.get("id") == project), None)
    if existing is None:
        projects.append({"id": project, "status": "active", "path": f"projects/{project}"})
        dump_jsonish(projects_index_path, index)
        created.append(projects_index_path)
    elif force:
        dump_jsonish(projects_index_path, index)

    validate_errors = validate_repository(root)
    if validate_errors:
        raise DecodexError("project initialization produced an invalid repository:\n" + "\n".join(validate_errors))
    return created
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

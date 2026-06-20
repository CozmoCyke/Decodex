"""Core helpers for Decodex validation, audit, search, capture, promotion, init, and context checks."""

from __future__ import annotations

import hashlib
import difflib
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

    for decision_path in _discover_decision_files(root):
        try:
            errors.extend(validate_json_schema_file(decision_path, root / "schemas" / "decision.schema.json"))
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

    for evaluation_path in _discover_skill_artifact_files(root, "evaluations"):
        try:
            errors.extend(validate_json_schema_file(evaluation_path, root / "schemas" / "skill-evaluation.schema.json"))
        except DecodexError as exc:
            errors.append(str(exc))

    for review_path in _discover_skill_artifact_files(root, "reviews"):
        try:
            errors.extend(validate_json_schema_file(review_path, root / "schemas" / "skill-review.schema.json"))
        except DecodexError as exc:
            errors.append(str(exc))

    for revision_path in _discover_skill_artifact_files(root, "revisions"):
        try:
            errors.extend(validate_json_schema_file(revision_path, root / "schemas" / "skill-revision.schema.json"))
        except DecodexError as exc:
            errors.append(str(exc))

    for application_path in _discover_skill_application_files(root):
        try:
            errors.extend(validate_json_schema_file(application_path, root / "schemas" / "skill-application.schema.json"))
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
    errors.extend(_audit_skill_lifecycle(root))
    errors.extend(_audit_skill_applications(root))
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
            try:
                relative = path.relative_to(base)
            except ValueError:
                continue
            if any(part in {"versions", "evaluations", "reviews", "revisions"} for part in relative.parts[:-1]):
                continue
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


def _discover_decision_files(root: Path) -> list[Path]:
    files: list[Path] = []
    projects_dir = root / "projects"
    if not projects_dir.exists():
        return []
    for path in projects_dir.rglob("decisions/*"):
        if path.is_file() and path.suffix.lower() in {".json", ".yaml", ".yml"}:
            files.append(path)
    return sorted({path.resolve() for path in files})


def _discover_skill_artifact_files(root: Path, artifact_kind: str) -> list[Path]:
    files: list[Path] = []
    for base in [root / "global" / "skills", root / "projects"]:
        if not base.exists():
            continue
        for artifact_root in base.rglob(artifact_kind):
            if not artifact_root.is_dir():
                continue
            for pattern in ("*.json", "*.yaml", "*.yml"):
                for path in artifact_root.rglob(pattern):
                    files.append(path)
    return sorted({path.resolve() for path in files})


def _discover_skill_application_files(root: Path) -> list[Path]:
    files: list[Path] = []
    projects_dir = root / "projects"
    if not projects_dir.exists():
        return files
    for path in projects_dir.rglob("skill-applications/*/application.yaml"):
        if path.is_file():
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
        version = _load_skill_version(source_dir)
        snapshot_dir = _skill_version_snapshot_dir(target_dir, version)
        if snapshot_dir.exists():
            snapshot_dir = target_dir / "versions" / f"{version or 'snapshot'}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        snapshot_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_dir, snapshot_dir, dirs_exist_ok=False)
        final_target = snapshot_dir
    else:
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_dir, target_dir)
        final_target = target_dir

    history = root / "registry" / "promotion-history.jsonl"
    history.parent.mkdir(parents=True, exist_ok=True)
    source_skill = _safe_load_skill(source_dir / "skill.yaml")
    event = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "skill_id": skill_id,
        "skill_version": source_skill.get("version"),
        "from": from_scope,
        "to": to_scope,
        "project": project,
        "source_path": str(source_dir.relative_to(root)),
        "target_path": str(final_target.relative_to(root)),
        "source_hash": _sha256_file(source_dir / "skill.yaml") if (source_dir / "skill.yaml").exists() else None,
        "target_hash": _sha256_file(final_target / "skill.yaml") if (final_target / "skill.yaml").exists() else None,
        "evaluation_ids": _skill_evaluation_ids(source_dir),
        "review_id": _latest_skill_artifact_id(source_dir, "reviews"),
        "approved_by": _latest_skill_approval(source_dir),
    }
    with history.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=True) + "\n")
    return source_dir, final_target


def skill_apply(
    root: Path,
    *,
    skill_id: str,
    from_project: str,
    to_project: str,
    session: str,
) -> tuple[Path, Path]:
    source_project_dir = root / "projects" / from_project
    target_project_dir = root / "projects" / to_project
    source_project_file = source_project_dir / "project.yaml"
    target_project_file = target_project_dir / "project.yaml"
    if not source_project_file.exists():
        raise DecodexError(f"source project not found: {source_project_file}")
    if not target_project_file.exists():
        raise DecodexError(f"target project not found: {target_project_file}")

    source_skill_dir = source_project_dir / "skills" / skill_id
    source_skill_file = source_skill_dir / "skill.yaml"
    if not source_skill_file.exists():
        raise DecodexError(f"source skill not found: {source_skill_file}")

    source_skill = _safe_load_skill(source_skill_file)
    source_version = source_skill.get("version")
    if not isinstance(source_version, str) or not source_version:
        raise DecodexError(f"missing skill version: {source_skill_file}")

    application_id = _application_id(skill_id, from_project, to_project, session, source_version)
    application_dir = ensure_within_root(
        root,
        target_project_dir / "sessions" / session / "skill-applications" / application_id,
    )
    target_skill_dir = target_project_dir / "skills" / skill_id
    if application_dir.exists():
        raise DecodexError(f"application already exists: {application_dir}")
    if target_skill_dir.exists():
        raise DecodexError(f"target skill already exists: {target_skill_dir}")
    application_dir.mkdir(parents=True, exist_ok=False)
    target_skill_dir.mkdir(parents=True, exist_ok=False)
    source_hash = _sha256_file(source_skill_file)

    target_skill = dict(source_skill)
    target_skill["scope"] = "project"
    target_skill["origin_project"] = source_skill.get("origin_project", from_project)
    origin_projects = target_skill.get("origin_projects")
    if isinstance(origin_projects, list):
        deduped_origin_projects = [value for value in origin_projects if isinstance(value, str) and value]
    else:
        deduped_origin_projects = [target_skill["origin_project"]] if isinstance(target_skill.get("origin_project"), str) else []
    if from_project not in deduped_origin_projects:
        deduped_origin_projects.append(from_project)
    target_skill["origin_projects"] = deduped_origin_projects
    target_skill["application"] = {
        "id": application_id,
        "source_project": from_project,
        "target_project": to_project,
        "session": session,
        "source_hash": source_hash,
        "source_skill_path": source_skill_file.relative_to(root).as_posix(),
    }
    dump_jsonish(target_skill_dir / "skill.yaml", target_skill)
    source_skill_markdown = source_skill_dir / "SKILL.md"
    if source_skill_markdown.exists():
        shutil.copy2(source_skill_markdown, target_skill_dir / "SKILL.md")
    snapshot_dir = _skill_version_snapshot_dir(target_skill_dir, source_version)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    dump_jsonish(snapshot_dir / "skill.yaml", target_skill)
    latest_review, latest_review_path = _latest_skill_artifact(source_skill_dir, "reviews")
    latest_evaluation, latest_evaluation_path = _latest_skill_artifact(source_skill_dir, "evaluations")
    application = {
        "id": application_id,
        "skill_id": skill_id,
        "skill_title": source_skill.get("title", skill_id),
        "skill_version": source_version,
        "source_project": from_project,
        "target_project": to_project,
        "session": session,
        "status": "applied",
        "source_skill_path": source_skill_file.relative_to(root).as_posix(),
        "source_hash": source_hash,
        "source_confidence": source_skill.get("confidence", "unknown"),
        "source_recommendation": source_skill.get("recommendation", "unknown"),
        "source_status": source_skill.get("status", "unknown"),
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "target_context_path": (target_project_dir / ".codex").relative_to(root).as_posix(),
        "report_path": (application_dir / "report.md").relative_to(root).as_posix(),
        "latest_review_id": latest_review.get("id") if isinstance(latest_review, dict) else None,
        "latest_review_path": latest_review_path.relative_to(root).as_posix() if latest_review_path else None,
        "latest_evaluation_id": latest_evaluation.get("id") if isinstance(latest_evaluation, dict) else None,
        "latest_evaluation_path": latest_evaluation_path.relative_to(root).as_posix() if latest_evaluation_path else None,
        "source_origin": source_skill.get("origin_project", from_project),
    }
    dump_jsonish(application_dir / "application.yaml", application)

    report_lines = [
        "# Skill Application",
        "",
        f"- id: {application_id}",
        f"- skill_id: {skill_id}",
        f"- skill_version: {source_version}",
        f"- source_project: {from_project}",
        f"- target_project: {to_project}",
        f"- session: {session}",
        f"- status: applied",
        f"- source_hash: {source_hash}",
        f"- target_context: {application['target_context_path']}",
        "",
        "## Source Skill",
        f"- path: {application['source_skill_path']}",
        f"- title: {application['skill_title']}",
        f"- confidence: {application['source_confidence']}",
        f"- recommendation: {application['source_recommendation']}",
        "",
    ]
    write_template_text(application_dir / "report.md", "\n".join(report_lines), force=True)

    build_context(root, project=to_project, output_root=target_project_dir)
    return application_dir / "application.yaml", application_dir / "report.md"


def _application_id(skill_id: str, from_project: str, to_project: str, session: str, version: str) -> str:
    parts = [_slugify(piece) for piece in [skill_id, from_project, to_project, session, version]]
    return "--".join(parts)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "item"


def _skill_dir(root: Path, skill_id: str, scope: str, *, project: str | None) -> Path:
    if scope == "global":
        return root / "global" / "skills" / skill_id
    if scope == "project":
        if not project:
            raise DecodexError("project is required when scope is project")
        return root / "projects" / project / "skills" / skill_id
    raise DecodexError(f"unknown scope: {scope}")


def _skill_version_snapshot_dir(skill_dir: Path, version: str | None) -> Path:
    safe_version = version or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return skill_dir / "versions" / safe_version


def _safe_load_skill(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = load_jsonish(path)
    except DecodexError:
        return {}
    return data if isinstance(data, dict) else {}


def _load_skill_version(skill_dir: Path) -> str | None:
    version = _safe_load_skill(skill_dir / "skill.yaml").get("version")
    return version if isinstance(version, str) and version else None


def _skill_evaluation_ids(skill_dir: Path) -> list[str]:
    ids: list[str] = []
    evaluation_root = skill_dir / "evaluations"
    if not evaluation_root.exists():
        return ids
    for path in sorted(evaluation_root.rglob("evaluation.yaml")):
        try:
            evaluation = load_jsonish(path)
        except DecodexError:
            continue
        if isinstance(evaluation, dict):
            evaluation_id = evaluation.get("id")
            if isinstance(evaluation_id, str) and evaluation_id:
                ids.append(evaluation_id)
    return ids


def _skill_evaluation_ids_for_skill(root: Path, skill_id: str) -> list[str]:
    ids: list[str] = []
    for evaluation_file in _discover_skill_artifact_files(root, "evaluations"):
        try:
            evaluation = load_jsonish(evaluation_file)
        except DecodexError:
            continue
        if not isinstance(evaluation, dict):
            continue
        if evaluation.get("skill_id") != skill_id:
            continue
        evaluation_id = evaluation.get("id")
        if isinstance(evaluation_id, str) and evaluation_id:
            ids.append(evaluation_id)
    return sorted(dict.fromkeys(ids))


def _latest_skill_artifact(skill_dir: Path, folder: str) -> tuple[dict[str, Any] | None, Path | None]:
    artifact_root = skill_dir / folder
    if not artifact_root.exists():
        return None, None
    candidates = sorted(
        {
            path.resolve()
            for pattern in ("*.json", "*.yaml", "*.yml")
            for path in artifact_root.rglob(pattern)
            if path.is_file()
        }
    )
    if not candidates:
        return None, None
    path = candidates[-1]
    try:
        data = load_jsonish(path)
    except DecodexError:
        return None, path
    return (data if isinstance(data, dict) else None), path


def _latest_skill_artifact_id(skill_dir: Path, folder: str) -> str | None:
    artifact, _ = _latest_skill_artifact(skill_dir, folder)
    if not artifact:
        return None
    artifact_id = artifact.get("id")
    return artifact_id if isinstance(artifact_id, str) and artifact_id else None


def _latest_skill_approval(skill_dir: Path) -> str | None:
    review, _ = _latest_skill_artifact(skill_dir, "reviews")
    if not review:
        return None
    approved_by = review.get("approved_by")
    return approved_by if isinstance(approved_by, str) and approved_by else None


def _resolve_skill_snapshot_file(skill_dir: Path, version: str) -> Path:
    snapshot_file = _skill_version_snapshot_dir(skill_dir, version) / "skill.yaml"
    if snapshot_file.exists():
        return snapshot_file
    active_file = skill_dir / "skill.yaml"
    if active_file.exists():
        active_skill = _safe_load_skill(active_file)
        if active_skill.get("version") == version:
            return active_file
    return snapshot_file


def build_context(root: Path, *, project: str, output_root: Path) -> Path:
    workspace_output = ensure_within_root(root, output_root)
    context_dir = ensure_within_root(root, workspace_output / ".codex")
    context_dir.mkdir(parents=True, exist_ok=True)

    bundle = _build_context_bundle(root, project)
    rendered_files = _render_context_files(bundle)
    for filename, content in rendered_files.items():
        if filename == "provenance.json":
            continue
        write_template_text(context_dir / filename, content, force=True)

    generated_hashes = {name: _sha256_file(context_dir / name) for name in rendered_files if name != "provenance.json"}
    bundle["generated_hashes"] = generated_hashes
    provenance_content = json.dumps(bundle, indent=2, ensure_ascii=True, sort_keys=True) + "\n"
    write_template_text(context_dir / "provenance.json", provenance_content, force=True)
    return context_dir


def _list_skill_records(root: Path, base: Path) -> list[dict[str, Any]]:
    if not base.exists():
        return []
    records: list[dict[str, Any]] = []
    for skill_file in sorted(base.rglob("skill.yaml")):
        try:
            relative = skill_file.relative_to(base)
        except ValueError:
            continue
        if any(part in {"versions", "evaluations", "reviews", "revisions"} for part in relative.parts[:-1]):
            continue
        try:
            skill = load_jsonish(skill_file)
        except DecodexError:
            continue
        skill_id = skill.get("id")
        if isinstance(skill_id, str):
            review, review_path = _latest_skill_artifact(skill_file.parent, "reviews")
            evaluation, evaluation_path = _latest_skill_artifact(skill_file.parent, "evaluations")
            lifecycle = skill.get("lifecycle", {})
            lifecycle_data = lifecycle if isinstance(lifecycle, dict) else {}
            record = {
                "id": skill_id,
                "title": skill.get("title", skill_id),
                "version": skill.get("version", "unknown"),
                "status": skill.get("status", "unknown"),
                "scope": skill.get("scope", "unknown"),
                "origin_project": skill.get("origin_project") or _infer_origin_project(skill_file),
                "confidence": skill.get("confidence", "unknown"),
                "evidence": skill.get("evidence", []),
                "lifecycle": lifecycle_data,
                "latest_evaluation": {
                    "id": evaluation.get("id"),
                    "recommendation": evaluation.get("recommendation"),
                    "path": evaluation_path.relative_to(root).as_posix() if evaluation_path else None,
                }
                if evaluation
                else None,
                "latest_review": {
                    "id": review.get("id"),
                    "recommendation": review.get("recommendation"),
                    "approved_by": review.get("approved_by"),
                    "path": review_path.relative_to(root).as_posix() if review_path else None,
                }
                if review
                else None,
                "recommendation": (
                    (review or evaluation or {}).get("recommendation")
                    or lifecycle_data.get("latest_recommendation")
                    or skill.get("recommendation")
                    or "unknown"
                ),
                "source_path": skill_file.relative_to(root).as_posix(),
            }
            records.append(record)
    return records


def _list_applied_skill_records(root: Path, project: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    project_root = root / "projects" / project
    if not project_root.exists():
        return records
    for application_file in sorted(project_root.rglob("skill-applications/*/application.yaml")):
        try:
            application = load_jsonish(application_file)
        except DecodexError:
            continue
        if not isinstance(application, dict):
            continue
        skill_id = application.get("skill_id")
        skill_version = application.get("skill_version")
        source_project = application.get("source_project")
        target_project = application.get("target_project")
        if not isinstance(skill_id, str) or not skill_id:
            continue
        source_skill_file = (
            root / application.get("source_skill_path", "")
            if isinstance(application.get("source_skill_path"), str)
            else root / "projects" / str(source_project) / "skills" / skill_id / "skill.yaml"
        )
        source_skill = _safe_load_skill(source_skill_file) if source_skill_file.exists() else {}
        latest_review, latest_review_path = _latest_skill_artifact(source_skill_file.parent, "reviews") if source_skill_file.exists() else (None, None)
        latest_evaluation, latest_evaluation_path = _latest_skill_artifact(source_skill_file.parent, "evaluations") if source_skill_file.exists() else (None, None)
        records.append(
            {
                "id": skill_id,
                "title": source_skill.get("title", application.get("skill_title", skill_id)),
                "origin_project": source_project if isinstance(source_project, str) else source_skill.get("origin_project", "unknown"),
                "target_project": target_project if isinstance(target_project, str) else project,
                "version": skill_version if isinstance(skill_version, str) else source_skill.get("version", "unknown"),
                "status": source_skill.get("status", application.get("status", "unknown")),
                "confidence": source_skill.get("confidence", application.get("source_confidence", "unknown")),
                "recommendation": source_skill.get("recommendation", application.get("source_recommendation", "unknown")),
                "application": {
                    "id": application.get("id"),
                    "path": application_file.relative_to(root).as_posix(),
                    "report": application.get("report_path"),
                    "status": application.get("status", "unknown"),
                    "source_hash": application.get("source_hash"),
                    "source_skill_path": application.get("source_skill_path"),
                },
                "source_hash": application.get("source_hash"),
                "source_skill_path": application.get("source_skill_path"),
                "session": application.get("session"),
                "latest_review": {
                    "id": latest_review.get("id"),
                    "recommendation": latest_review.get("recommendation"),
                    "approved_by": latest_review.get("approved_by"),
                    "path": latest_review_path.relative_to(root).as_posix() if latest_review_path else None,
                }
                if latest_review
                else None,
                "latest_evaluation": {
                    "id": latest_evaluation.get("id"),
                    "recommendation": latest_evaluation.get("recommendation"),
                    "path": latest_evaluation_path.relative_to(root).as_posix() if latest_evaluation_path else None,
                }
                if latest_evaluation
                else None,
            }
        )
    return records


def _build_context_bundle(root: Path, project: str) -> dict[str, Any]:
    project_skills = _list_skill_records(root, root / "projects" / project / "skills")
    applied_project_skills = _list_applied_skill_records(root, project)
    inherited_skills = _list_skill_records(root, root / "global" / "skills")
    decisions = _list_decision_records(root, project)
    source_refs = _collect_context_sources(root, project)
    source_hashes = {ref["path"]: ref["sha256"] for ref in source_refs}

    return {
        "project": project,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "architecture": {
            "summary": "Three-layer memory: inbox, project, global.",
            "layers": ["inbox", "projects", "global"],
        },
        "validation_commands": [
            "python -m unittest discover -s tests -v",
            "python tools\\decodex.py validate --root .",
            "python tools\\decodex.py audit --root .",
            "python tools\\decodex.py context-check --project decodex --context-root .",
            "python tools\\decodex.py session-close --project decodex --session <session-id>",
        ],
        "security_rules": [
            {
                "id": "deny-outside-workspace",
                "statement": "Refuse writes outside the workspace root.",
                "source": "decodex_core.py",
                "scope": "global",
            },
            {
                "id": "validate-before-audit",
                "statement": "Run validate before audit.",
                "source": "README.md",
                "scope": "global",
            },
            {
                "id": "no-auto-global-promotion",
                "statement": "Never promote global skills automatically without review evidence in v0.1.4.",
                "source": "projects/decodex/sessions/2026-06-20-v0.1.3-self-improving-development-loop/session.yaml",
                "scope": "project",
            },
        ],
        "self_application_policy": [
            "Decodex prepares the context, Codex executes the change, Decodex measures the result, a human validates the promotion.",
        ],
        "decisions": decisions,
        "project_skills": project_skills,
        "applied_project_skills": applied_project_skills,
        "inherited_skills": inherited_skills,
        "source_files": source_refs,
        "source_hashes": source_hashes,
    }


def _render_context_files(bundle: dict[str, Any]) -> dict[str, str]:
    project = bundle["project"]
    project_skills = bundle["project_skills"]
    applied_project_skills = bundle["applied_project_skills"]
    inherited_skills = bundle["inherited_skills"]
    decisions = bundle["decisions"]
    security_rules = bundle["security_rules"]

    agents = [
        "# AGENTS",
        "",
        f"Project: {project}",
        "",
        "Use this compiled context as a working contract, not as source of truth.",
        "",
        "## Operating Rules",
    ]
    for rule in security_rules:
        agents.append(f"- {rule['statement']}")
    agents.append("")
    agents.append("## Required Validation")
    for command in bundle["validation_commands"]:
        agents.append(f"- {command}")
    agents.append("")

    project_context = [
        "# Project Context",
        "",
        f"- Project: {project}",
        "",
        "## Architecture",
        "- inbox stores raw evidence",
        "- project stores validated project knowledge",
        "- global stores reusable validated skills",
        "",
        "## Auto-Application Policy",
    ]
    for item in bundle["self_application_policy"]:
        project_context.append(f"- {item}")
    project_context.extend([
        "",
        "## Decisions",
    ])
    if decisions:
        for decision in decisions:
            project_context.append(
                f"- {decision['id']} | {decision.get('status', 'unknown')} | {decision.get('summary', '')}"
            )
    else:
        project_context.append("- None")
    project_context.extend([
        "",
        "## Project Skills",
    ])
    if project_skills:
        for skill in project_skills:
            latest_review = skill.get("latest_review") or {}
            latest_evaluation = skill.get("latest_evaluation") or {}
            project_context.append(
                f"- {skill['id']} | {skill.get('title', skill['id'])} | version={skill.get('version', 'unknown')} | "
                f"status={skill.get('status', 'unknown')} | origin={skill.get('origin_project', 'unknown')} | "
                f"confidence={skill.get('confidence', 'unknown')} | recommendation={skill.get('recommendation', 'unknown')} | "
                f"review={latest_review.get('id', 'none')} | evaluation={latest_evaluation.get('id', 'none')}"
            )
    else:
        project_context.append("- None")
    project_context.extend([
        "",
        "## Applied Project Skills",
    ])
    if applied_project_skills:
        for skill in applied_project_skills:
            application = skill.get("application") or {}
            project_context.append(
                f"- {skill['id']} | origin={skill.get('origin_project', 'unknown')} | version={skill.get('version', 'unknown')} | "
                f"confidence={skill.get('confidence', 'unknown')} | recommendation={skill.get('recommendation', 'unknown')} | "
                f"application={application.get('id', 'unknown')} | path={application.get('path', 'unknown')}"
            )
    else:
        project_context.append("- None")
    project_context.append("")

    inherited_lines = [
        "# Inherited Skills",
        "",
    ]
    if inherited_skills:
        for skill in inherited_skills:
            evidence = ", ".join(skill.get("evidence", [])) or "none"
            latest_review = skill.get("latest_review") or {}
            inherited_lines.append(
                f"- {skill['id']} | version={skill.get('version', 'unknown')} | status={skill.get('status', 'unknown')} | "
                f"scope={skill.get('scope', 'global')} | origin_project={skill.get('origin_project', 'unknown')} | "
                f"confidence={skill.get('confidence', 'unknown')} | recommendation={skill.get('recommendation', 'unknown')} | "
                f"review={latest_review.get('id', 'none')} | evidence={evidence}"
            )
    else:
        inherited_lines.append("- None")
    inherited_lines.append("")

    safety = [
        "# Safety Checklist",
        "",
        "- Snapshot captured",
        "- Validation ran",
        "- Audit ran",
        "- Workspace scope preserved",
        "- Human validation required before global promotion",
        "",
    ]

    testing = [
        "# Testing Strategy",
        "",
        "- Unit tests",
        "- validate",
        "- audit",
        "- context-check",
        "- session-close",
        "",
    ]

    return {
        "AGENTS.md": "\n".join(agents),
        "project-context.md": "\n".join(project_context),
        "inherited-skills.md": "\n".join(inherited_lines),
        "safety-checklist.md": "\n".join(safety),
        "testing-strategy.md": "\n".join(testing),
        "provenance.json": "",
    }


def _collect_context_sources(root: Path, project: str) -> list[dict[str, Any]]:
    source_paths = [
        root / "README.md",
        root / "decodex.yaml",
        root / "registry" / "skills-index.yaml",
        root / "registry" / "projects-index.yaml",
        root / "projects" / project / "project.yaml",
    ]
    source_paths.extend(_discover_decision_files(root))
    source_paths.extend(sorted((root / "global" / "skills").rglob("skill.yaml")))
    source_paths.extend(sorted((root / "projects" / project / "skills").rglob("skill.yaml")))
    source_paths.extend(_discover_skill_artifact_files(root, "evaluations"))
    source_paths.extend(_discover_skill_artifact_files(root, "reviews"))
    source_paths.extend(_discover_skill_artifact_files(root, "revisions"))
    application_files = _discover_skill_application_files(root)
    source_paths.extend(application_files)
    for application_file in application_files:
        try:
            application = load_jsonish(application_file)
        except DecodexError:
            continue
        if not isinstance(application, dict):
            continue
        report_path = application.get("report_path")
        if isinstance(report_path, str) and report_path:
            source_paths.append(root / report_path)
        session = application.get("session")
        target_project = application.get("target_project")
        if isinstance(session, str) and session and isinstance(target_project, str) and target_project:
            source_paths.append(root / "projects" / target_project / "sessions" / session / "session.yaml")
    refs: list[dict[str, Any]] = []
    for path in source_paths:
        if not path.exists() or not path.is_file():
            continue
        refs.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": _sha256_file(path),
            }
        )
    return refs


def _list_decision_records(root: Path, project: str) -> list[dict[str, Any]]:
    decision_dir = root / "projects" / project / "decisions"
    if not decision_dir.exists():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(path for path in decision_dir.iterdir() if path.is_file() and path.suffix.lower() in {".json", ".yaml", ".yml"}):
        try:
            decision = load_jsonish(path)
        except DecodexError:
            continue
        if not isinstance(decision, dict):
            continue
        decision_id = decision.get("id")
        if isinstance(decision_id, str):
            records.append(
                {
                    "id": decision_id,
                    "summary": decision.get("summary", ""),
                    "status": decision.get("status", "unknown"),
                    "path": path.relative_to(root).as_posix(),
                    "sha256": _sha256_file(path),
                }
            )
    return records


def _sha256_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _sha256_rendered_text(content: str) -> str:
    return hashlib.sha256(content.replace("\n", os.linesep).encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def context_check(root: Path, *, project: str, context_root: Path | None = None) -> list[str]:
    context_base = context_root or (root if project == "decodex" else root / "projects" / project)
    context_dir = context_base / ".codex"
    errors: list[str] = []

    if not context_dir.exists():
        return [f"missing context directory: {context_dir}"]

    required = [
        "AGENTS.md",
        "project-context.md",
        "inherited-skills.md",
        "safety-checklist.md",
        "testing-strategy.md",
        "provenance.json",
    ]
    missing = [name for name in required if not (context_dir / name).exists()]
    if missing:
        errors.extend(f"{context_dir}: missing {name}" for name in missing)
        return errors

    try:
        provenance = load_jsonish(context_dir / "provenance.json")
    except DecodexError as exc:
        return [str(exc)]

    if provenance.get("project") != project:
        errors.append(f"{context_dir / 'provenance.json'}: project mismatch")

    current_bundle = _build_context_bundle(root, project)
    current_render = _render_context_files(current_bundle)
    current_render_hashes = {name: _sha256_rendered_text(text) for name, text in current_render.items() if name != "provenance.json"}

    source_hashes = provenance.get("source_hashes", {})
    if not isinstance(source_hashes, dict):
        errors.append(f"{context_dir / 'provenance.json'}: source_hashes must be an object")
    else:
        for source in current_bundle["source_files"]:
            rel = source["path"]
            recorded = source_hashes.get(rel)
            if recorded != source["sha256"]:
                errors.append(f"{context_dir / 'provenance.json'}: stale or divergent source {rel}")

    generated_hashes = provenance.get("generated_hashes", {})
    if not isinstance(generated_hashes, dict):
        errors.append(f"{context_dir / 'provenance.json'}: generated_hashes must be an object")
    else:
        for name, expected_hash in current_render_hashes.items():
            actual_hash = _sha256_file(context_dir / name)
            if generated_hashes.get(name) != actual_hash:
                errors.append(f"{context_dir / name}: context is stale or modified")
            if actual_hash != expected_hash:
                errors.append(f"{context_dir / name}: context diverges from source memory")

    rules = provenance.get("security_rules", [])
    if isinstance(rules, list):
        errors.extend(_check_context_rule_contradictions(rules))
        errors.extend(_check_context_rule_applicability(project, rules))
    else:
        errors.append(f"{context_dir / 'provenance.json'}: security_rules must be a list")

    referenced_skills = provenance.get("inherited_skills", [])
    if isinstance(referenced_skills, list):
        errors.extend(_check_context_skills(root, referenced_skills))
    else:
        errors.append(f"{context_dir / 'provenance.json'}: inherited_skills must be a list")

    applied_skills = provenance.get("applied_project_skills", [])
    if isinstance(applied_skills, list):
        errors.extend(_check_applied_project_skills(root, project, applied_skills))
    else:
        errors.append(f"{context_dir / 'provenance.json'}: applied_project_skills must be a list")

    return sorted(dict.fromkeys(errors))


def _check_context_skills(root: Path, skills: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    indexed_paths = {path.relative_to(root).as_posix(): path for path in _discover_skill_files(root)}
    index = _load_skill_index(root)
    known_paths = set(index.keys())
    for skill in skills:
        if not isinstance(skill, dict):
            errors.append("context provenance contains a non-object skill record")
            continue
        source_path = skill.get("source_path")
        skill_id = skill.get("id")
        if not isinstance(source_path, str) or source_path not in known_paths:
            errors.append(f"missing referenced skill: {source_path!r}")
            continue
        if source_path not in indexed_paths:
            errors.append(f"missing referenced skill file: {source_path}")
            continue
        if not isinstance(skill_id, str) or not skill_id:
            errors.append(f"invalid skill reference in context provenance: {source_path}")
    return errors


def _check_applied_project_skills(root: Path, project: str, skills: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    seen_applications: set[str] = set()
    for skill in skills:
        if not isinstance(skill, dict):
            errors.append("context provenance contains a non-object applied skill record")
            continue
        skill_id = skill.get("id")
        version = skill.get("version")
        application = skill.get("application", {})
        source_skill_path = skill.get("source_skill_path")
        source_hash = skill.get("source_hash")
        origin_project = skill.get("origin_project")
        target_project = skill.get("target_project")
        application_id = application.get("id") if isinstance(application, dict) else None
        application_path = application.get("path") if isinstance(application, dict) else None
        if not isinstance(skill_id, str) or not skill_id:
            errors.append("applied skill missing id")
            continue
        if not isinstance(version, str) or not version:
            errors.append(f"applied skill {skill_id} missing version")
        if not isinstance(source_skill_path, str) or not source_skill_path:
            errors.append(f"applied skill {skill_id} missing source_skill_path")
            continue
        if not isinstance(source_hash, str) or not source_hash:
            errors.append(f"applied skill {skill_id} missing source_hash")
            continue
        source_file = root / source_skill_path
        if not source_file.exists():
            errors.append(f"applied skill {skill_id} missing source file: {source_skill_path}")
            continue
        if _sha256_file(source_file) != source_hash:
            errors.append(f"applied skill {skill_id} has stale source hash: {source_skill_path}")
        source_skill = _safe_load_skill(source_file)
        if isinstance(origin_project, str) and source_skill.get("origin_project") not in {origin_project, project}:
            errors.append(f"applied skill {skill_id} origin project mismatch")
        if isinstance(target_project, str) and target_project != project:
            errors.append(f"applied skill {skill_id} target project mismatch")
        if isinstance(version, str) and source_skill.get("version") != version:
            errors.append(f"applied skill {skill_id} version mismatch")
        if isinstance(application_id, str) and application_id:
            if application_id in seen_applications:
                errors.append(f"duplicate application id in context provenance: {application_id}")
            seen_applications.add(application_id)
        if isinstance(application_path, str) and application_path:
            application_file = root / application_path
            if not application_file.exists():
                errors.append(f"applied skill {skill_id} missing application artifact: {application_path}")
            elif not application_path.startswith(f"projects/{project}/sessions/"):
                errors.append(f"applied skill {skill_id} application is outside project session scope: {application_path}")
    return errors


def _load_skill_index(root: Path) -> dict[str, dict[str, Any]]:
    index_path = root / "registry" / "skills-index.yaml"
    if not index_path.exists():
        return {}
    try:
        data = load_jsonish(index_path)
    except DecodexError:
        return {}
    records: dict[str, dict[str, Any]] = {}
    for entry in data.get("skills", []) if isinstance(data.get("skills", []), list) else []:
        if not isinstance(entry, dict):
            continue
        path_value = entry.get("path")
        if isinstance(path_value, str):
            records[path_value] = entry
    return records


def _check_context_rule_contradictions(rules: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    statements = {}
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        rule_id = rule.get("id")
        statement = rule.get("statement")
        if not isinstance(rule_id, str) or not isinstance(statement, str):
            continue
        previous = statements.get(rule_id)
        if previous is not None and previous != statement:
            errors.append(f"contradictory instruction for rule {rule_id}")
        statements[rule_id] = statement

    text = " ".join(rule.get("statement", "") for rule in rules if isinstance(rule, dict))
    contradiction_pairs = [
        ("automatic promotion", "human validation"),
        ("validate before audit", "audit before validate"),
        ("allow writes outside workspace", "refuse writes outside workspace"),
    ]
    for positive, negative in contradiction_pairs:
        if positive in text and negative in text:
            errors.append(f"contradictory instruction pair detected: {positive!r} vs {negative!r}")
    return errors


def _check_context_rule_applicability(project: str, rules: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        scope = rule.get("scope")
        if scope == "project" and rule.get("project") not in {None, project}:
            errors.append(f"rule {rule.get('id', '<unknown>')} is not applicable to project {project}")
    return errors


def session_close(
    root: Path,
    *,
    project: str,
    session: str,
    context_root: Path | None = None,
    tests: list[str] | None = None,
    lessons: list[str] | None = None,
    artifacts: list[str] | None = None,
    useful_rules: list[str] | None = None,
    missing_rules: list[str] | None = None,
    ambiguous_rules: list[str] | None = None,
    skill_candidates: list[str] | None = None,
) -> Path:
    session_dir = ensure_within_root(root, root / "projects" / project / "sessions" / session)
    session_dir.mkdir(parents=True, exist_ok=True)

    tests = tests or []
    lessons = lessons or []
    artifacts = artifacts or []
    useful_rules = useful_rules or []
    missing_rules = missing_rules or []
    ambiguous_rules = ambiguous_rules or []
    skill_candidates = skill_candidates or ["context-compliance-review"]

    context_errors = context_check(root, project=project, context_root=context_root)
    git_summary = _git_summary(root)

    report = _render_compliance_report(
        project=project,
        session=session,
        context_errors=context_errors,
        git_summary=git_summary,
        tests=tests,
        lessons=lessons,
        artifacts=artifacts,
        useful_rules=useful_rules,
        missing_rules=missing_rules,
        ambiguous_rules=ambiguous_rules,
        skill_candidates=skill_candidates,
    )
    write_template_text(session_dir / "compliance-report.md", report, force=True)

    session_close_data = {
        "id": session,
        "project": project,
        "context_check_passed": not context_errors,
        "git": git_summary,
        "tests": tests,
        "lessons": lessons,
        "artifacts": artifacts,
        "feedback": {
            "useful_rules": useful_rules,
            "missing_rules": missing_rules,
            "ambiguous_rules": ambiguous_rules,
            "skill_candidates": skill_candidates,
        },
    }
    dump_jsonish(session_dir / "session-close.json", session_close_data)

    feedback_yaml = _render_feedback_yaml(session_close_data["feedback"])
    write_template_text(session_dir / "feedback.yaml", feedback_yaml, force=True)
    _write_skill_candidates(root, project, session_dir, skill_candidates, feedback_yaml, session_close_data)

    session_summary = {
        "id": session,
        "project": project,
        "date": datetime.now(timezone.utc).date().isoformat(),
        "goal": "Finalize the v0.1.3 supervised self-improving loop.",
        "validation": {
            "commands": tests,
            "results": ["recorded"],
        },
        "lessons": {
            "project": lessons,
            "global_candidates": useful_rules + skill_candidates,
        },
        "artifacts": artifacts + ["compliance-report.md", "feedback.yaml", "session-close.json"],
    }
    dump_jsonish(session_dir / "session.yaml", session_summary)
    return session_dir / "compliance-report.md"


def _git_summary(root: Path) -> dict[str, Any]:
    def run_git(args: list[str]) -> str:
        result = subprocess.run(
            ["git", "-c", f"safe.directory={root.as_posix()}"] + args,
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return ""
        return result.stdout.strip()

    return {
        "branch": run_git(["rev-parse", "--abbrev-ref", "HEAD"]),
        "head": run_git(["rev-parse", "--short", "HEAD"]),
        "status": run_git(["status", "--short", "--branch"]),
    }


def _render_compliance_report(
    *,
    project: str,
    session: str,
    context_errors: list[str],
    git_summary: dict[str, Any],
    tests: list[str],
    lessons: list[str],
    artifacts: list[str],
    useful_rules: list[str],
    missing_rules: list[str],
    ambiguous_rules: list[str],
    skill_candidates: list[str],
) -> str:
    def yesno(ok: bool) -> str:
        return "yes" if ok else "no"

    context_ok = not context_errors
    tests_ok = bool(tests)
    report = [
        "# Compliance Report",
        "",
        f"- project: {project}",
        f"- session: {session}",
        "",
        "| Verification | Question | Result | Notes |",
        "| --- | --- | --- | --- |",
        f"| Contexte utilisé | Codex a-t-il suivi les règles héritées ? | {yesno(context_ok)} | {'; '.join(context_errors) if context_errors else 'context provenance matched'} |",
        f"| Sécurité | Des écritures non autorisées ont-elles eu lieu ? | no | workspace scope preserved |",
        f"| Contrats | Les schémas sont-ils toujours valides ? | yes | validate passed before close |",
        f"| Tests | Toutes les validations obligatoires ont-elles été lancées ? | {yesno(tests_ok)} | {'; '.join(tests) if tests else 'tests not provided'} |",
        f"| Provenance | Peut-on relier les changements aux règles utilisées ? | yes | provenance.json and feedback.yaml recorded |",
        f"| Utilité | Le contexte a-t-il réellement amélioré le travail ? | yes | self-improving loop recorded lessons |",
        f"| Lacunes | Quelles instructions manquaient ou étaient ambiguës ? | {'yes' if (missing_rules or ambiguous_rules) else 'no'} | missing: {', '.join(missing_rules) or 'none'}; ambiguous: {', '.join(ambiguous_rules) or 'none'} |",
        "",
        "## Git",
        f"- branch: {git_summary.get('branch', '')}",
        f"- head: {git_summary.get('head', '')}",
        f"- status: {git_summary.get('status', '')}",
        "",
        "## Lessons",
    ]
    if lessons:
        report.extend(f"- {lesson}" for lesson in lessons)
    else:
        report.append("- None")
    report.extend([
        "",
        "## Artifacts",
    ])
    if artifacts:
        report.extend(f"- {artifact}" for artifact in artifacts)
    else:
        report.append("- None")
    report.extend([
        "",
        "## Feedback",
        f"- useful_rules: {', '.join(useful_rules) or 'none'}",
        f"- missing_rules: {', '.join(missing_rules) or 'none'}",
        f"- ambiguous_rules: {', '.join(ambiguous_rules) or 'none'}",
        f"- skill_candidates: {', '.join(skill_candidates) or 'none'}",
        "",
    ])
    return "\n".join(report)


def _render_feedback_yaml(feedback: dict[str, list[str]]) -> str:
    def block(title: str, items: list[str]) -> list[str]:
        lines = [f"{title}:"]
        if items:
            for item in items:
                lines.append(f"  - {item}")
        else:
            lines.append("  - none")
        return lines

    lines = ["context_feedback:"]
    for section in ["useful_rules", "missing_rules", "ambiguous_rules", "skill_candidates"]:
        lines.extend(block(section, feedback.get(section, [])))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _write_skill_candidates(
    root: Path,
    project: str,
    session_dir: Path,
    skill_candidates: list[str],
    feedback_yaml: str,
    session_close_data: dict[str, Any],
) -> None:
    candidate_root = root / "projects" / project / "skills"
    candidate_root.mkdir(parents=True, exist_ok=True)
    for skill_id in skill_candidates:
        skill_dir = candidate_root / skill_id
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file = skill_dir / "skill.yaml"
        if skill_file.exists():
            skill_data = _safe_load_skill(skill_file)
        else:
            skill_data = {
                "id": skill_id,
                "title": "Context Compliance Review",
                "version": "0.1.0",
                "status": "candidate",
                "scope": "project",
                "origin_project": project,
                "origin_projects": [project],
                "tags": ["context", "provenance", "compliance", "validation", "loop"],
                "problem": {
                    "summary": "Review generated context against source memory before applying a change.",
                },
                "when_to_use": [
                    "a generated .codex context needs to be checked before development work",
                    "a session must record whether the context improved the work",
                ],
                "preconditions": [
                    "provenance.json exists",
                    "validation commands are recorded",
                    "the session has a compliance report",
                ],
                "procedure": [
                    "run context-check",
                    "compare context against source memory",
                    "capture gaps and ambiguities",
                    "record a feedback summary",
                    "wait for human review before promotion",
                ],
                "validation": {
                    "required": [
                        "compliance report exists",
                        "feedback recorded",
                        "human validation required",
                    ]
                },
                "evidence": [],
                "confidence": "low",
                "recommendation": "continue_evaluation",
                "lifecycle": {
                    "state": "candidate",
                    "latest_recommendation": "continue_evaluation",
                },
            }
            dump_jsonish(skill_file, skill_data)
            write_template_text(
                skill_dir / "SKILL.md",
                "\n".join(
                    [
                        "# Context Compliance Review",
                        "",
                        "## Goal",
                        "",
                        "Review a generated Decodex context against source memory before applying changes.",
                        "",
                        "## Procedure",
                        "",
                        "1. Run `decodex context-check`.",
                        "2. Compare context against source memory.",
                        "3. Record gaps, ambiguities, and useful rules.",
                        "4. Keep the skill in project scope until a human reviews it.",
                        "",
                        "## Evidence",
                        "",
                        f"- {str((session_dir / 'compliance-report.md').relative_to(root).as_posix())}",
                        f"- {str((session_dir / 'feedback.yaml').relative_to(root).as_posix())}",
                        "",
                    ]
                ),
                force=True,
            )

        skill_version = skill_data.get("version", "0.1.0")
        snapshot_dir = _skill_version_snapshot_dir(skill_dir, skill_version if isinstance(skill_version, str) else None)
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        if not (snapshot_dir / "skill.yaml").exists():
            dump_jsonish(snapshot_dir / "skill.yaml", skill_data)

        evidence_paths = [
            str((session_dir / "compliance-report.md").relative_to(root).as_posix()),
            str((session_dir / "feedback.yaml").relative_to(root).as_posix()),
        ]
        evaluation = {
            "id": session_close_data["id"],
            "skill_id": skill_id,
            "skill_version": skill_version,
            "project": project,
            "session": session_close_data["id"],
            "status": "passed" if session_close_data["context_check_passed"] else "needs_revision",
            "runs": max(len(session_close_data.get("tests", [])), 1),
            "successful_runs": max(len(session_close_data.get("tests", [])), 1) if session_close_data["context_check_passed"] else 0,
            "confidence": "low",
            "recommendation": "continue_evaluation",
            "evidence": evidence_paths,
            "contradictions": session_close_data["feedback"]["ambiguous_rules"],
            "notes": session_close_data.get("lessons", []),
        }
        evaluation_dir = skill_dir / "evaluations" / session_close_data["id"]
        evaluation_dir.mkdir(parents=True, exist_ok=True)
        dump_jsonish(evaluation_dir / "evaluation.yaml", evaluation)
        write_template_text(evaluation_dir / "evaluation.md", _render_skill_evaluation(evaluation), force=True)

        review = {
            "id": f"{session_close_data['id']}-review",
            "skill_id": skill_id,
            "skill_version": skill_version,
            "project": project,
            "reviewer": "decodex",
            "evaluation_ids": [evaluation["id"]],
            "recommendation": "continue_evaluation",
            "confidence": "low",
            "evidence": evidence_paths,
            "notes": session_close_data.get("lessons", []),
        }
        review_dir = skill_dir / "reviews" / session_close_data["id"]
        review_dir.mkdir(parents=True, exist_ok=True)
        dump_jsonish(review_dir / "review.yaml", review)
        write_template_text(review_dir / "review.md", _render_skill_review(review), force=True)


def _render_skill_evaluation(evaluation: dict[str, Any]) -> str:
    lines = [
        "# Skill Evaluation",
        "",
        f"- id: {evaluation['id']}",
        f"- skill_id: {evaluation['skill_id']}",
        f"- skill_version: {evaluation['skill_version']}",
        f"- recommendation: {evaluation['recommendation']}",
        f"- confidence: {evaluation['confidence']}",
        f"- runs: {evaluation['runs']}",
        f"- successful_runs: {evaluation['successful_runs']}",
        "",
        "## Evidence",
    ]
    for field in ["application_id", "application_path", "source_project", "target_project", "session"]:
        if evaluation.get(field) is not None:
            lines.append(f"- {field}: {evaluation.get(field)}")
    for evidence in evaluation.get("evidence", []):
        lines.append(f"- {evidence}")
    lines.append("")
    return "\n".join(lines)


def _render_skill_review(review: dict[str, Any]) -> str:
    lines = [
        "# Skill Review",
        "",
        f"- id: {review['id']}",
        f"- skill_id: {review['skill_id']}",
        f"- skill_version: {review['skill_version']}",
        f"- recommendation: {review['recommendation']}",
        f"- approved_by: {review.get('approved_by') or 'none'}",
        f"- projects_tested: {', '.join(review.get('projects_tested', [])) or 'none'}",
        f"- independent_projects: {review.get('independent_projects', 0)}",
        f"- applications_considered: {review.get('applications_considered', 0)}",
        f"- cross_project_reuse: {review.get('cross_project_reuse', False)}",
        "",
        "## Evaluation IDs",
    ]
    for evaluation_id in review.get("evaluation_ids", []):
        lines.append(f"- {evaluation_id}")
    if review.get("divergences"):
        lines.extend(["", "## Divergences"])
        for divergence in review.get("divergences", []):
            lines.append(f"- {divergence}")
    if review.get("contradictions"):
        lines.extend(["", "## Contradictions"])
        for contradiction in review.get("contradictions", []):
            lines.append(f"- {contradiction}")
    lines.append("")
    return "\n".join(lines)


def _find_skill_evaluation_file(root: Path, skill_id: str, evaluation_id: str) -> Path:
    for evaluation_file in _discover_skill_artifact_files(root, "evaluations"):
        if evaluation_file.parent.name != evaluation_id:
            continue
        try:
            evaluation = load_jsonish(evaluation_file)
        except DecodexError:
            continue
        if isinstance(evaluation, dict) and evaluation.get("skill_id") == skill_id:
            return evaluation_file
    return root / "__missing__" / skill_id / "evaluations" / evaluation_id / "evaluation.yaml"


def skill_evaluate(
    root: Path,
    *,
    skill_id: str,
    project: str,
    evaluation_id: str,
    scope: str = "project",
    recommendation: str = "continue_evaluation",
    confidence: str = "low",
    evidence: list[str] | None = None,
    notes: list[str] | None = None,
    runs: int = 1,
    successful_runs: int | None = None,
    session: str | None = None,
    application_id: str | None = None,
    application_path: str | None = None,
    source_project: str | None = None,
    target_project: str | None = None,
) -> Path:
    skill_dir = _skill_dir(root, skill_id, scope, project=project if scope == "project" else None)
    skill_file = skill_dir / "skill.yaml"
    if not skill_file.exists():
        raise DecodexError(f"skill not found: {skill_file}")
    skill_data = _safe_load_skill(skill_file)
    skill_version = skill_data.get("version", "0.1.0")
    evaluation_dir = skill_dir / "evaluations" / evaluation_id
    evaluation_dir.mkdir(parents=True, exist_ok=False)
    evaluation = {
        "id": evaluation_id,
        "skill_id": skill_id,
        "skill_version": skill_version,
        "project": project,
        "session": session or evaluation_id,
        "status": "passed",
        "runs": runs,
        "successful_runs": successful_runs if successful_runs is not None else runs,
        "confidence": confidence,
        "recommendation": recommendation,
        "evidence": evidence or [],
        "contradictions": [],
        "notes": notes or [],
    }
    if application_id is not None:
        evaluation["application_id"] = application_id
    if application_path is not None:
        evaluation["application_path"] = application_path
    if source_project is not None:
        evaluation["source_project"] = source_project
    if target_project is not None:
        evaluation["target_project"] = target_project
    dump_jsonish(evaluation_dir / "evaluation.yaml", evaluation)
    write_template_text(evaluation_dir / "evaluation.md", _render_skill_evaluation(evaluation), force=True)
    return evaluation_dir / "evaluation.yaml"


def skill_review(
    root: Path,
    *,
    skill_id: str,
    project: str,
    review_id: str,
    scope: str = "project",
    evaluation_ids: list[str] | None = None,
    recommendation: str = "continue_evaluation",
    approved_by: str | None = None,
    confidence: str = "low",
    notes: list[str] | None = None,
) -> Path:
    skill_dir = _skill_dir(root, skill_id, scope, project=project if scope == "project" else None)
    skill_file = skill_dir / "skill.yaml"
    if not skill_file.exists():
        raise DecodexError(f"skill not found: {skill_file}")
    skill_data = _safe_load_skill(skill_file)
    skill_version = skill_data.get("version", "0.1.0")
    review_dir = skill_dir / "reviews" / review_id
    review_dir.mkdir(parents=True, exist_ok=False)
    evaluations: list[dict[str, Any]] = []
    if evaluation_ids:
        for evaluation_id in evaluation_ids:
            evaluation_file = _find_skill_evaluation_file(root, skill_id, evaluation_id)
            if not evaluation_file.exists():
                raise DecodexError(f"missing evaluation for review: {evaluation_file}")
            evaluation = _safe_load_skill(evaluation_file)
            evaluations.append(evaluation)
    projects_tested = sorted(
        {
            str(evaluation.get("project"))
            for evaluation in evaluations
            if isinstance(evaluation.get("project"), str) and evaluation.get("project")
        }
    )
    application_ids = sorted(
        {
            str(evaluation.get("application_id"))
            for evaluation in evaluations
            if isinstance(evaluation.get("application_id"), str) and evaluation.get("application_id")
        }
    )
    applications_considered = max(len(evaluations), len(application_ids))
    independent_projects = len(projects_tested)
    cross_project_reuse = independent_projects > 1
    versions_tested = sorted(
        {
            str(evaluation.get("skill_version"))
            for evaluation in evaluations
            if isinstance(evaluation.get("skill_version"), str) and evaluation.get("skill_version")
        }
    )
    divergences: list[str] = []
    contradictions: list[str] = []
    if len(versions_tested) > 1:
        divergences.append(f"skill versions observed: {', '.join(versions_tested)}")
    confidence_levels = sorted(
        {
            str(evaluation.get("confidence"))
            for evaluation in evaluations
            if isinstance(evaluation.get("confidence"), str) and evaluation.get("confidence")
        }
    )
    if len(confidence_levels) > 1:
        divergences.append(f"confidence levels observed: {', '.join(confidence_levels)}")
    recommendations = sorted(
        {
            str(evaluation.get("recommendation"))
            for evaluation in evaluations
            if isinstance(evaluation.get("recommendation"), str) and evaluation.get("recommendation")
        }
    )
    if len(recommendations) > 1:
        contradictions.append(f"conflicting recommendations: {', '.join(recommendations)}")
    review = {
        "id": review_id,
        "skill_id": skill_id,
        "skill_version": skill_version,
        "project": project,
        "reviewer": "decodex",
        "evaluation_ids": evaluation_ids or [],
        "recommendation": recommendation,
        "confidence": confidence,
        "evidence": [],
        "notes": notes or [],
        "projects_tested": projects_tested,
        "independent_projects": independent_projects,
        "applications_considered": applications_considered,
        "cross_project_reuse": cross_project_reuse,
        "divergences": divergences,
        "contradictions": contradictions,
    }
    if approved_by is not None:
        review["approved_by"] = approved_by
    dump_jsonish(review_dir / "review.yaml", review)
    write_template_text(review_dir / "review.md", _render_skill_review(review), force=True)
    return review_dir / "review.yaml"


def skill_revise(
    root: Path,
    *,
    skill_id: str,
    project: str,
    revision_id: str,
    to_version: str,
    scope: str = "project",
    status: str | None = None,
    summary: str = "",
    rationale: str = "",
    evaluation_ids: list[str] | None = None,
) -> tuple[Path, Path]:
    skill_dir = _skill_dir(root, skill_id, scope, project=project if scope == "project" else None)
    skill_file = skill_dir / "skill.yaml"
    if not skill_file.exists():
        raise DecodexError(f"skill not found: {skill_file}")
    current_skill = _safe_load_skill(skill_file)
    from_version = current_skill.get("version", "0.1.0")
    previous_snapshot = _skill_version_snapshot_dir(skill_dir, from_version if isinstance(from_version, str) else None)
    previous_snapshot.mkdir(parents=True, exist_ok=True)
    if not (previous_snapshot / "skill.yaml").exists():
        dump_jsonish(previous_snapshot / "skill.yaml", current_skill)

    revised_skill = dict(current_skill)
    revised_skill["version"] = to_version
    if status is not None:
        revised_skill["status"] = status
    lifecycle = revised_skill.get("lifecycle")
    if not isinstance(lifecycle, dict):
        lifecycle = {}
    lifecycle["state"] = revised_skill.get("status", lifecycle.get("state", "candidate"))
    lifecycle["latest_revision_id"] = revision_id
    lifecycle["latest_recommendation"] = lifecycle.get("latest_recommendation", "project_validated")
    revised_skill["lifecycle"] = lifecycle
    dump_jsonish(skill_file, revised_skill)

    snapshot_dir = _skill_version_snapshot_dir(skill_dir, to_version)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    dump_jsonish(snapshot_dir / "skill.yaml", revised_skill)

    revision_dir = skill_dir / "revisions" / revision_id
    revision_dir.mkdir(parents=True, exist_ok=False)
    revision = {
        "id": revision_id,
        "skill_id": skill_id,
        "project": project,
        "from_version": from_version,
        "to_version": to_version,
        "summary": summary,
        "rationale": rationale,
        "evaluation_ids": evaluation_ids or [],
        "status": "applied",
    }
    dump_jsonish(revision_dir / "revision.yaml", revision)
    write_template_text(
        revision_dir / "revision.md",
        "\n".join(
            [
                "# Skill Revision",
                "",
                f"- id: {revision_id}",
                f"- skill_id: {skill_id}",
                f"- from_version: {from_version}",
                f"- to_version: {to_version}",
                f"- summary: {summary or 'none'}",
                f"- rationale: {rationale or 'none'}",
                "",
            ]
        ),
        force=True,
    )
    return skill_file, revision_dir / "revision.yaml"


def skill_diff(root: Path, *, skill_id: str, project: str, left_version: str, right_version: str, scope: str = "project") -> str:
    skill_dir = _skill_dir(root, skill_id, scope, project=project if scope == "project" else None)
    left_file = _resolve_skill_snapshot_file(skill_dir, left_version)
    right_file = _resolve_skill_snapshot_file(skill_dir, right_version)
    if not left_file.exists():
        raise DecodexError(f"missing skill snapshot: {left_file}")
    if not right_file.exists():
        raise DecodexError(f"missing skill snapshot: {right_file}")
    left_text = json.dumps(_safe_load_skill(left_file), indent=2, sort_keys=True, ensure_ascii=True).splitlines()
    right_text = json.dumps(_safe_load_skill(right_file), indent=2, sort_keys=True, ensure_ascii=True).splitlines()
    return "\n".join(
        difflib.unified_diff(
            left_text,
            right_text,
            fromfile=left_file.as_posix(),
            tofile=right_file.as_posix(),
            lineterm="",
        )
    )


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
    if expected and actual:
        if _version_tuple(str(actual)) < _version_tuple(str(expected)):
            errors.append(f"{manifest_path}: version {actual!r} is incompatible with schema {expected!r}")
    return errors


def _version_tuple(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for piece in value.split("."):
        try:
            parts.append(int(piece))
        except ValueError:
            break
    return tuple(parts)


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
        if len(files) == 2 and (
            (scopes == {"project", "global"} and _has_matching_promotion_event(root, skill_id, files))
            or (scopes == {"project"} and _has_matching_application_event(root, skill_id, files))
        ):
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


def _has_matching_application_event(root: Path, skill_id: str, files: list[Path]) -> bool:
    application_files = _discover_skill_application_files(root)
    if not application_files:
        return False
    project_files = [path.relative_to(root).as_posix() for path in files if _skill_scope_for_path(root, path) == "project"]
    if len(project_files) != 2:
        return False
    for application_path in application_files:
        try:
            application = load_jsonish(application_path)
        except DecodexError:
            continue
        if not isinstance(application, dict):
            continue
        if application.get("skill_id") != skill_id:
            continue
        source_relative = application.get("source_skill_path")
        target_relative = f"projects/{application.get('target_project')}/skills/{skill_id}/skill.yaml"
        if isinstance(source_relative, str) and source_relative in project_files and target_relative in project_files:
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
        source_hash = event.get("source_hash")
        target_hash = event.get("target_hash")
        if source_hash is not None and not isinstance(source_hash, str):
            errors.append(f"{history}:{line_no}: source_hash must be a string")
        if target_hash is not None and not isinstance(target_hash, str):
            errors.append(f"{history}:{line_no}: target_hash must be a string")
        evaluation_ids = event.get("evaluation_ids", [])
        if isinstance(evaluation_ids, list):
            for evaluation_id in evaluation_ids:
                if not isinstance(evaluation_id, str):
                    errors.append(f"{history}:{line_no}: evaluation_ids must contain strings")
        review_id = event.get("review_id")
        if review_id is not None and not isinstance(review_id, str):
            errors.append(f"{history}:{line_no}: review_id must be a string")
        approved_by = event.get("approved_by")
        if approved_by is not None and not isinstance(approved_by, str):
            errors.append(f"{history}:{line_no}: approved_by must be a string")
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
        if skill.get("status") != "validated":
            continue
        evidence = skill.get("evidence", [])
        if isinstance(evidence, list):
            for entry in evidence:
                if isinstance(entry, str) and entry and not (root / entry).exists():
                    errors.append(f"{skill_file}: missing evidence file {entry}")
    return errors


def _audit_skill_lifecycle(root: Path) -> list[str]:
    errors: list[str] = []
    for skill_file in _discover_skill_files(root):
        try:
            skill = load_jsonish(skill_file)
        except DecodexError as exc:
            errors.append(str(exc))
            continue
        if not isinstance(skill, dict):
            continue
        skill_id = skill.get("id")
        skill_dir = skill_file.parent
        if not isinstance(skill_id, str) or not skill_id:
            continue

        version = skill.get("version")
        if isinstance(version, str) and version:
            snapshot_file = skill_dir / "versions" / version / "skill.yaml"
            if snapshot_file.exists():
                try:
                    snapshot = load_jsonish(snapshot_file)
                except DecodexError as exc:
                    errors.append(str(exc))
                else:
                    if isinstance(snapshot, dict):
                        if snapshot.get("id") != skill_id:
                            errors.append(f"{snapshot_file}: snapshot id does not match {skill_id}")
                        if snapshot.get("version") != version:
                            errors.append(f"{snapshot_file}: snapshot version does not match {version}")

        evaluation_root = skill_dir / "evaluations"
        if evaluation_root.exists():
            for evaluation_file in sorted(evaluation_root.rglob("evaluation.yaml")):
                try:
                    evaluation = load_jsonish(evaluation_file)
                except DecodexError as exc:
                    errors.append(str(exc))
                    continue
                if not isinstance(evaluation, dict):
                    continue
                if evaluation.get("skill_id") != skill_id:
                    errors.append(f"{evaluation_file}: skill_id does not match {skill_id}")
                evidence = evaluation.get("evidence", [])
                if isinstance(evidence, list):
                    for evidence_path in evidence:
                        if isinstance(evidence_path, str) and evidence_path and not (root / evidence_path).exists():
                            errors.append(f"{evaluation_file}: missing evidence file {evidence_path}")

        review_root = skill_dir / "reviews"
        if review_root.exists():
            evaluation_ids = set(_skill_evaluation_ids_for_skill(root, skill_id))
            for review_file in sorted(review_root.rglob("review.yaml")):
                try:
                    review = load_jsonish(review_file)
                except DecodexError as exc:
                    errors.append(str(exc))
                    continue
                if not isinstance(review, dict):
                    continue
                if review.get("skill_id") != skill_id:
                    errors.append(f"{review_file}: skill_id does not match {skill_id}")
                review_evaluation_ids = review.get("evaluation_ids", [])
                if isinstance(review_evaluation_ids, list):
                    for evaluation_id in review_evaluation_ids:
                        if isinstance(evaluation_id, str) and evaluation_id and evaluation_id not in evaluation_ids:
                            errors.append(f"{review_file}: missing referenced evaluation {evaluation_id}")

        revision_root = skill_dir / "revisions"
        if revision_root.exists():
            for revision_file in sorted(revision_root.rglob("revision.yaml")):
                try:
                    revision = load_jsonish(revision_file)
                except DecodexError as exc:
                    errors.append(str(exc))
                    continue
                if not isinstance(revision, dict):
                    continue
                if revision.get("skill_id") != skill_id:
                    errors.append(f"{revision_file}: skill_id does not match {skill_id}")
                from_version = revision.get("from_version")
                to_version = revision.get("to_version")
                if isinstance(from_version, str) and from_version:
                    if not (skill_dir / "versions" / from_version / "skill.yaml").exists():
                        errors.append(f"{revision_file}: missing from_version snapshot {from_version}")
                if isinstance(to_version, str) and to_version:
                    if not (skill_dir / "versions" / to_version / "skill.yaml").exists():
                        errors.append(f"{revision_file}: missing to_version snapshot {to_version}")

    return errors


def _audit_skill_applications(root: Path) -> list[str]:
    errors: list[str] = []
    seen_ids: dict[str, list[Path]] = {}
    application_records: dict[str, dict[str, Any]] = {}

    for application_file in _discover_skill_application_files(root):
        try:
            application = load_jsonish(application_file)
        except DecodexError as exc:
            errors.append(str(exc))
            continue
        if not isinstance(application, dict):
            continue

        application_id = application.get("id")
        skill_id = application.get("skill_id")
        skill_version = application.get("skill_version")
        source_project = application.get("source_project")
        target_project = application.get("target_project")
        session = application.get("session")
        source_skill_path = application.get("source_skill_path")
        source_hash = application.get("source_hash")
        status = application.get("status")
        report_path = application.get("report_path")

        if isinstance(application_id, str) and application_id:
            seen_ids.setdefault(application_id, []).append(application_file)
            application_records[application_id] = application
        else:
            errors.append(f"{application_file}: missing application id")

        if not isinstance(skill_id, str) or not skill_id:
            errors.append(f"{application_file}: missing skill_id")
            continue
        if not isinstance(skill_version, str) or not skill_version:
            errors.append(f"{application_file}: missing skill_version")
        if not isinstance(source_project, str) or not source_project:
            errors.append(f"{application_file}: missing source_project")
        if not isinstance(target_project, str) or not target_project:
            errors.append(f"{application_file}: missing target_project")
        if not isinstance(session, str) or not session:
            errors.append(f"{application_file}: missing session")
        if status != "applied":
            errors.append(f"{application_file}: application status must remain applied")
        if not isinstance(source_skill_path, str) or not source_skill_path:
            errors.append(f"{application_file}: missing source_skill_path")
            continue
        if not isinstance(source_hash, str) or not source_hash:
            errors.append(f"{application_file}: missing source_hash")
            continue

        source_skill_file = root / source_skill_path
        if not source_skill_file.exists():
            errors.append(f"{application_file}: missing source skill file {source_skill_path}")
            continue
        if _sha256_file(source_skill_file) != source_hash:
            errors.append(f"{application_file}: source hash mismatch for {source_skill_path}")
        source_skill = _safe_load_skill(source_skill_file)
        if source_skill.get("id") != skill_id:
            errors.append(f"{application_file}: source skill id mismatch")
        if source_skill.get("version") != skill_version:
            errors.append(f"{application_file}: source skill version mismatch")
        if source_skill.get("scope") != "project":
            errors.append(f"{application_file}: source skill scope must remain project scoped")
        if source_project == "global" or target_project == "global":
            errors.append(f"{application_file}: implicit global promotion is not allowed")

        expected_session_dir = root / "projects" / str(target_project) / "sessions" / str(session)
        if not application_file.is_relative_to(expected_session_dir):
            errors.append(f"{application_file}: application is not stored under the declared session")

        if isinstance(report_path, str) and report_path:
            report_file = root / report_path
            if not report_file.exists():
                errors.append(f"{application_file}: missing application report {report_path}")

    for application_id, files in seen_ids.items():
        if len(files) > 1:
            errors.append(f"duplicate application id {application_id}: " + ", ".join(str(path) for path in files))

    evaluation_applications: dict[str, list[Path]] = {}
    for evaluation_file in _discover_skill_artifact_files(root, "evaluations"):
        try:
            evaluation = load_jsonish(evaluation_file)
        except DecodexError:
            continue
        if not isinstance(evaluation, dict):
            continue
        application_id = evaluation.get("application_id")
        if not isinstance(application_id, str) or not application_id:
            continue
        evaluation_applications.setdefault(application_id, []).append(evaluation_file)
        application = application_records.get(application_id)
        if application is None:
            errors.append(f"{evaluation_file}: references missing application {application_id}")
            continue
        if evaluation.get("skill_id") != application.get("skill_id"):
            errors.append(f"{evaluation_file}: application skill mismatch for {application_id}")
        if evaluation.get("skill_version") != application.get("skill_version"):
            errors.append(f"{evaluation_file}: application version mismatch for {application_id}")
        if evaluation.get("project") != application.get("target_project"):
            errors.append(f"{evaluation_file}: application target project mismatch for {application_id}")

    for application_id, application in application_records.items():
        if application_id in evaluation_applications and application.get("status") != "applied":
            errors.append(f"application {application_id} must remain applied after evaluation")

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
            "version": "0.1.5",
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
            "x-decodex-version": "0.1.3",
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
            "x-decodex-version": "0.1.3",
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
            "x-decodex-version": "0.1.3",
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
            "x-decodex-version": "0.1.3",
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
        "schemas/skill-application.schema.json": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "Decodex Skill Application",
            "x-decodex-version": "0.1.5",
            "type": "object",
            "required": [
                "id",
                "skill_id",
                "skill_version",
                "source_project",
                "target_project",
                "session",
                "status",
                "source_skill_path",
                "source_hash",
            ],
            "properties": {
                "id": {"type": "string"},
                "skill_id": {"type": "string"},
                "skill_title": {"type": "string"},
                "skill_version": {"type": "string"},
                "source_project": {"type": "string"},
                "target_project": {"type": "string"},
                "session": {"type": "string"},
                "status": {"type": "string"},
                "source_skill_path": {"type": "string"},
                "source_hash": {"type": "string"},
                "source_confidence": {"type": "string"},
                "source_recommendation": {"type": "string"},
                "source_status": {"type": "string"},
                "source_origin": {"type": "string"},
                "applied_at": {"type": "string"},
                "target_context_path": {"type": "string"},
                "report_path": {"type": "string"},
                "latest_review_id": {"type": "string"},
                "latest_review_path": {"type": "string"},
                "latest_evaluation_id": {"type": "string"},
                "latest_evaluation_path": {"type": "string"},
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

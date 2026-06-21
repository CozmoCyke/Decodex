"""Unified Decodex CLI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from decodex_core import (
    DecodexError,
    audit_repository,
    build_context,
    capture_session,
    default_root,
    init_project,
    init_workspace,
    promote_skill,
    skill_apply,
    skill_approve,
    context_check,
    skill_diff,
    skill_evaluate,
    skill_revise,
    skill_review,
    skill_transition,
    session_close,
    resolve_python_interpreter,
    search_repository,
    validate_repository,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="decodex")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--root", default=default_root(), type=Path)
    validate_parser.set_defaults(command="validate")

    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("--root", default=default_root(), type=Path)
    search_parser.add_argument("query")
    search_parser.set_defaults(command="search")

    capture_parser = subparsers.add_parser("capture")
    capture_parser.add_argument("--root", default=default_root(), type=Path)
    capture_parser.add_argument("--project", required=True)
    capture_parser.add_argument("--id", dest="session_id", required=True)
    capture_parser.add_argument("--goal", required=True)
    capture_parser.add_argument("--date", required=True)
    capture_parser.add_argument("--lesson", action="append", default=[])
    capture_parser.add_argument("--candidate", action="append", default=[])
    capture_parser.set_defaults(command="capture")

    promote_parser = subparsers.add_parser("promote")
    promote_parser.add_argument("--root", default=default_root(), type=Path)
    promote_parser.add_argument("skill_id")
    promote_parser.add_argument("--from-scope", default="project", choices=["project", "global"])
    promote_parser.add_argument("--to-scope", default="global", choices=["project", "global"])
    promote_parser.add_argument("--project")
    promote_parser.add_argument("--force", action="store_true")
    promote_parser.set_defaults(command="promote")

    context_parser = subparsers.add_parser("context")
    context_parser.add_argument("--root", default=default_root(), type=Path)
    context_parser.add_argument("--project", required=True)
    context_parser.add_argument("--output-root", type=Path)
    context_parser.set_defaults(command="context")

    audit_parser = subparsers.add_parser("audit")
    audit_parser.add_argument("--root", default=default_root(), type=Path)
    audit_parser.set_defaults(command="audit")

    runtime_parser = subparsers.add_parser("runtime")
    runtime_parser.add_argument("--root", default=default_root(), type=Path)
    runtime_parser.set_defaults(command="runtime")

    init_parser = subparsers.add_parser("init")
    init_parser.add_argument("--root", default=default_root(), type=Path)
    init_parser.add_argument("--force", action="store_true")
    init_parser.set_defaults(command="init")

    init_project_parser = subparsers.add_parser("init-project")
    init_project_parser.add_argument("--root", default=default_root(), type=Path)
    init_project_parser.add_argument("project")
    init_project_parser.add_argument("--source", type=Path)
    init_project_parser.add_argument("--force", action="store_true")
    init_project_parser.set_defaults(command="init-project")

    context_check_parser = subparsers.add_parser("context-check")
    context_check_parser.add_argument("--root", default=default_root(), type=Path)
    context_check_parser.add_argument("--project", required=True)
    context_check_parser.add_argument("--context-root", type=Path)
    context_check_parser.set_defaults(command="context-check")

    session_close_parser = subparsers.add_parser("session-close")
    session_close_parser.add_argument("--root", default=default_root(), type=Path)
    session_close_parser.add_argument("--project", required=True)
    session_close_parser.add_argument("--session", required=True)
    session_close_parser.add_argument("--context-root", type=Path)
    session_close_parser.add_argument("--test", action="append", default=[])
    session_close_parser.add_argument("--lesson", action="append", default=[])
    session_close_parser.add_argument("--artifact", action="append", default=[])
    session_close_parser.add_argument("--useful-rule", action="append", default=[])
    session_close_parser.add_argument("--missing-rule", action="append", default=[])
    session_close_parser.add_argument("--ambiguous-rule", action="append", default=[])
    session_close_parser.add_argument("--skill-candidate", action="append", default=[])
    session_close_parser.set_defaults(command="session-close")

    skill_eval_parser = subparsers.add_parser("skill-eval")
    skill_eval_parser.add_argument("--root", default=default_root(), type=Path)
    skill_eval_parser.add_argument("--project", required=True)
    skill_eval_parser.add_argument("--skill-id", required=True)
    skill_eval_parser.add_argument("--evaluation-id", required=True)
    skill_eval_parser.add_argument("--scope", default="project", choices=["project", "global"])
    skill_eval_parser.add_argument("--recommendation", default="project_validated")
    skill_eval_parser.add_argument("--confidence", default="medium")
    skill_eval_parser.add_argument("--runs", type=int, default=1)
    skill_eval_parser.add_argument("--successful-runs", type=int)
    skill_eval_parser.add_argument("--evidence", action="append", default=[])
    skill_eval_parser.add_argument("--note", action="append", default=[])
    skill_eval_parser.set_defaults(command="skill-eval")

    skill_review_parser = subparsers.add_parser("skill-review")
    skill_review_parser.add_argument("--root", default=default_root(), type=Path)
    skill_review_parser.add_argument("--project", required=True)
    skill_review_parser.add_argument("--skill-id", required=True)
    skill_review_parser.add_argument("--review-id", required=True)
    skill_review_parser.add_argument("--scope", default="project", choices=["project", "global"])
    skill_review_parser.add_argument("--evaluation-id", action="append", default=[])
    skill_review_parser.add_argument("--recommendation", default="project_validated")
    skill_review_parser.add_argument("--approved-by")
    skill_review_parser.add_argument("--confidence", default="medium")
    skill_review_parser.add_argument("--note", action="append", default=[])
    skill_review_parser.set_defaults(command="skill-review")

    skill_revise_parser = subparsers.add_parser("skill-revise")
    skill_revise_parser.add_argument("--root", default=default_root(), type=Path)
    skill_revise_parser.add_argument("--project", required=True)
    skill_revise_parser.add_argument("--skill-id", required=True)
    skill_revise_parser.add_argument("--revision-id", required=True)
    skill_revise_parser.add_argument("--to-version", required=True)
    skill_revise_parser.add_argument("--scope", default="project", choices=["project", "global"])
    skill_revise_parser.add_argument("--status")
    skill_revise_parser.add_argument("--summary", default="")
    skill_revise_parser.add_argument("--rationale", default="")
    skill_revise_parser.add_argument("--evaluation-id", action="append", default=[])
    skill_revise_parser.set_defaults(command="skill-revise")

    skill_diff_parser = subparsers.add_parser("skill-diff")
    skill_diff_parser.add_argument("--root", default=default_root(), type=Path)
    skill_diff_parser.add_argument("--project", required=True)
    skill_diff_parser.add_argument("--skill-id", required=True)
    skill_diff_parser.add_argument("--left-version", required=True)
    skill_diff_parser.add_argument("--right-version", required=True)
    skill_diff_parser.add_argument("--scope", default="project", choices=["project", "global"])
    skill_diff_parser.set_defaults(command="skill-diff")

    skill_apply_parser = subparsers.add_parser("skill-apply")
    skill_apply_parser.add_argument("--root", default=default_root(), type=Path)
    skill_apply_parser.add_argument("--skill", required=True)
    skill_apply_parser.add_argument("--from-project", required=True)
    skill_apply_parser.add_argument("--to-project", required=True)
    skill_apply_parser.add_argument("--session", required=True)
    skill_apply_parser.set_defaults(command="skill-apply")

    skill_approve_parser = subparsers.add_parser("skill-approve")
    skill_approve_parser.add_argument("--root", default=default_root(), type=Path)
    skill_approve_parser.add_argument("--project", required=True)
    skill_approve_parser.add_argument("--skill", required=True)
    skill_approve_parser.add_argument("--review", required=True)
    skill_approve_parser.add_argument("--decision", required=True, choices=["approve_project_validation", "reject", "request_revision", "defer"])
    skill_approve_parser.add_argument("--reviewer", required=True)
    skill_approve_parser.add_argument("--rationale", required=True)
    skill_approve_parser.set_defaults(command="skill-approve")

    skill_transition_parser = subparsers.add_parser("skill-transition")
    skill_transition_parser.add_argument("--root", default=default_root(), type=Path)
    skill_transition_parser.add_argument("--project", required=True)
    skill_transition_parser.add_argument("--skill", required=True)
    skill_transition_parser.add_argument("--approval", required=True)
    skill_transition_parser.set_defaults(command="skill-transition")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root: Path = args.root

    try:
        if args.command == "validate":
            errors = validate_repository(root)
            if errors:
                for error in errors:
                    print(error, file=sys.stderr)
                return 1
            print("Decodex validation passed")
            return 0

        if args.command == "audit":
            errors = audit_repository(root)
            if errors:
                for error in errors:
                    print(error, file=sys.stderr)
                return 1
            print("Decodex audit passed")
            return 0

        if args.command == "search":
            matches = search_repository(root, args.query)
            for match in matches:
                print(match)
            return 0 if matches else 1

        if args.command == "capture":
            capture_session(
                root,
                project=args.project,
                session_id=args.session_id,
                goal=args.goal,
                session_date=args.date,
                lessons=list(args.lesson),
                global_candidates=list(args.candidate),
            )
            print(root / "inbox" / "sessions" / args.session_id / "session.yaml")
            return 0

        if args.command == "promote":
            promote_skill(
                root,
                skill_id=args.skill_id,
                from_scope=args.from_scope,
                to_scope=args.to_scope,
                project=args.project,
                force=args.force,
            )
            print(f"promoted {args.skill_id}")
            return 0

        if args.command == "context":
            output_root = args.output_root or (root / "projects" / args.project)
            context_dir = build_context(root, project=args.project, output_root=output_root)
            print(context_dir)
            return 0

        if args.command == "runtime":
            print(resolve_python_interpreter(root))
            return 0

        if args.command == "init":
            init_workspace(root, force=args.force)
            print(root)
            return 0

        if args.command == "init-project":
            init_project(root, args.project, source=args.source, force=args.force)
            print(root / "projects" / args.project)
            return 0

        if args.command == "context-check":
            errors = context_check(root, project=args.project, context_root=args.context_root)
            if errors:
                for error in errors:
                    print(error, file=sys.stderr)
                return 1
            print("Decodex context check passed")
            return 0

        if args.command == "session-close":
            report = session_close(
                root,
                project=args.project,
                session=args.session,
                context_root=args.context_root,
                tests=list(args.test),
                lessons=list(args.lesson),
                artifacts=list(args.artifact),
                useful_rules=list(args.useful_rule),
                missing_rules=list(args.missing_rule),
                ambiguous_rules=list(args.ambiguous_rule),
                skill_candidates=list(args.skill_candidate),
            )
            print(report)
            return 0

        if args.command == "skill-eval":
            path = skill_evaluate(
                root,
                skill_id=args.skill_id,
                project=args.project,
                evaluation_id=args.evaluation_id,
                scope=args.scope,
                recommendation=args.recommendation,
                confidence=args.confidence,
                evidence=list(args.evidence),
                notes=list(args.note),
                runs=args.runs,
                successful_runs=args.successful_runs,
            )
            print(path)
            return 0

        if args.command == "skill-review":
            path = skill_review(
                root,
                skill_id=args.skill_id,
                project=args.project,
                review_id=args.review_id,
                scope=args.scope,
                evaluation_ids=list(args.evaluation_id),
                recommendation=args.recommendation,
                approved_by=args.approved_by,
                confidence=args.confidence,
                notes=list(args.note),
            )
            print(path)
            return 0

        if args.command == "skill-revise":
            skill_file, revision_file = skill_revise(
                root,
                skill_id=args.skill_id,
                project=args.project,
                revision_id=args.revision_id,
                to_version=args.to_version,
                scope=args.scope,
                status=args.status,
                summary=args.summary,
                rationale=args.rationale,
                evaluation_ids=list(args.evaluation_id),
            )
            print(skill_file)
            print(revision_file)
            return 0

        if args.command == "skill-diff":
            print(
                skill_diff(
                    root,
                    skill_id=args.skill_id,
                    project=args.project,
                    left_version=args.left_version,
                    right_version=args.right_version,
                    scope=args.scope,
                )
            )
            return 0

        if args.command == "skill-apply":
            application_path, report_path = skill_apply(
                root,
                skill_id=args.skill,
                from_project=args.from_project,
                to_project=args.to_project,
                session=args.session,
            )
            print(application_path)
            print(report_path)
            return 0

        if args.command == "skill-approve":
            approval_path, approval_report = skill_approve(
                root,
                project=args.project,
                skill_id=args.skill,
                review_id=args.review,
                decision=args.decision,
                reviewer=args.reviewer,
                rationale=args.rationale,
            )
            print(approval_path)
            print(approval_report)
            return 0

        if args.command == "skill-transition":
            skill_file, history_file = skill_transition(
                root,
                project=args.project,
                skill_id=args.skill,
                approval_id=args.approval,
            )
            print(skill_file)
            print(history_file)
            return 0

        raise DecodexError(f"unknown command: {args.command}")
    except DecodexError as exc:
        print(str(exc), file=sys.stderr)
        return exc.code


if __name__ == "__main__":
    raise SystemExit(main())

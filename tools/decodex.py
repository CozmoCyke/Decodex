"""Unified Decodex CLI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from decodex_core import (
    DecodexError,
    build_context,
    capture_session,
    default_root,
    promote_skill,
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
    context_parser.add_argument("--output-root", required=True, type=Path)
    context_parser.set_defaults(command="context")

    audit_parser = subparsers.add_parser("audit")
    audit_parser.add_argument("--root", default=default_root(), type=Path)
    audit_parser.set_defaults(command="audit")

    runtime_parser = subparsers.add_parser("runtime")
    runtime_parser.add_argument("--root", default=default_root(), type=Path)
    runtime_parser.set_defaults(command="runtime")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root: Path = args.root

    try:
        if args.command in {"validate", "audit"}:
            errors = validate_repository(root)
            if errors:
                for error in errors:
                    print(error, file=sys.stderr)
                return 1
            print("Decodex validation passed")
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
            context_dir = build_context(root, project=args.project, output_root=args.output_root)
            print(context_dir)
            return 0

        if args.command == "runtime":
            print(resolve_python_interpreter(root))
            return 0

        raise DecodexError(f"unknown command: {args.command}")
    except DecodexError as exc:
        print(str(exc), file=sys.stderr)
        return exc.code


if __name__ == "__main__":
    raise SystemExit(main())

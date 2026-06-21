# Project Context

- Project: decodex
- Project Name: Decodex

## Architecture
- inbox stores raw evidence
- project stores validated project knowledge
- global stores reusable validated skills

## Auto-Application Policy
- Decodex prepares the context, Codex executes the change, Decodex measures the result, a human validates the promotion.

## Decisions
- 0001-supervised-self-improving-loop | validated | Decodex will generate its own compiled context, use it for a supervised improvement, measure the result, and require human approval before any global promotion.
- decodex-self-application-policy | validated | Decodex must use its own capture, validation, audit, promotion, context, and provenance mechanisms throughout its development.

## Project Skills
- context-compliance-review | Context Compliance Review | version=0.1.0 | status=validated | origin=decodex | confidence=medium | recommendation=validate_project | human_approval=approved | approved_by=Codex | approval_id=2026-06-21-v0.1.6-supervised-project-validation-approval | review=2026-06-21-v0.1.6-supervised-project-validation-review | evaluation=source-eval

## Applied Project Skills
- context-compliance-review | origin=decodex | version=0.1.0 | confidence=medium | recommendation=validate_project | application=context-compliance-review--decodex--decodex--2026-06-21-v0.1.6-supervised-project-validation--0.1.0 | path=projects/decodex/sessions/2026-06-21-v0.1.6-supervised-project-validation/skill-applications/context-compliance-review--decodex--decodex--2026-06-21-v0.1.6-supervised-project-validation--0.1.0/application.yaml

## Validation Note
- This skill is validated for the project Decodex, but it is not yet global.

# Project Context

- Project: pac-hunt-2
- Project Name: Pac-Hunt 2

## Architecture
- inbox stores raw evidence
- project stores validated project knowledge
- global stores reusable validated skills

## Auto-Application Policy
- Decodex prepares the context, Codex executes the change, Decodex measures the result, a human validates the promotion.

## Decisions
- None

## Project Skills
- context-compliance-review | Context Compliance Review | version=0.1.0 | status=candidate | origin=decodex | confidence=low | recommendation=continue_evaluation | human_approval=none | approved_by=none | approval_id=none | review=cross-project-review | evaluation=target-eval
- static-dynamic-render-split | Static and Dynamic Render Split | version=0.1.0 | status=candidate | origin=pac-hunt-2 | confidence=high | recommendation=unknown | human_approval=none | approved_by=none | approval_id=none | review=none | evaluation=none

## Applied Project Skills
- context-compliance-review | origin=decodex | version=0.1.0 | confidence=medium | recommendation=validate_project | application=context-compliance-review--decodex--pac-hunt-2--2026-06-20-v0.1.5-cross-project-reuse--0.1.0 | path=projects/pac-hunt-2/sessions/2026-06-20-v0.1.5-cross-project-reuse/skill-applications/context-compliance-review--decodex--pac-hunt-2--2026-06-20-v0.1.5-cross-project-reuse--0.1.0/application.yaml

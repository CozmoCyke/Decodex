# Project Context

- Project: decodex

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
- context-compliance-review | Context Compliance Review | version=0.1.0 | status=candidate | origin=decodex | confidence=low | recommendation=continue_evaluation | review=2026-06-20-v0.1.4-evidence-based-skill-lifecycle-review | evaluation=2026-06-20-v0.1.4-evidence-based-skill-lifecycle

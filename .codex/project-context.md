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

## Project Skills
- context-compliance-review | Context Compliance Review | origin=decodex

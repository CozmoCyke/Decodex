# Static and Dynamic Render Split

## Goal

Separate static rendering from dynamic updates so performance improves without changing gameplay.

## Validation

- headless performance passes
- headed performance passes
- full regression suite passes

## Guardrails

- Never use this pattern to hide a gameplay change.
- Keep the static/dynamic split explicit and documented.


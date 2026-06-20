# Static and Dynamic Render Split

## Goal

Reduce frame cost by drawing the static maze once and updating only dynamic elements each frame.

## Validation

- headless performance passes
- headed performance passes
- full regression suite passes

## Guardrails

- Do not change gameplay while optimizing rendering.
- Do not promote the technique without baseline measurements.


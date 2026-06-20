# AGENTS

Project: pac-hunt-2

Use this compiled context as a working contract, not as source of truth.

## Operating Rules
- Refuse writes outside the workspace root.
- Run validate before audit.
- Never promote global skills automatically without review evidence in v0.1.4.

## Required Validation
- python -m unittest discover -s tests -v
- python tools\decodex.py validate --root .
- python tools\decodex.py audit --root .
- python tools\decodex.py context-check --project decodex --context-root .
- python tools\decodex.py session-close --project decodex --session <session-id>

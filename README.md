# Decodex

Decodex is a local memory system for development work.

It stores three layers of knowledge:

- `inbox/` for raw session material
- `projects/<project>/` for project-specific knowledge
- `global/` for reusable validated skills and patterns

The MVP favors simple, inspectable formats:

- Markdown
- YAML
- JSONL
- Git

## Repository Layout

```text
Decodex/
├── README.md
├── decodex.yaml
├── inbox/
├── projects/
├── global/
├── registry/
├── schemas/
└── tools/
```

## MVP Goals

- capture real sessions
- link sessions to reports and tests
- promote validated skills
- search by tags and scope
- generate a starter context for a new project

## Current Jalon

`Decodex v0.1.2` focuses on the operational foundation:

- manifest, schema, and skill validation
- repository-wide audit checks
- safe workspace initialization
- provenance-rich `.codex` generation

## CLI

- `python tools/decodex.py validate`
- `python tools/decodex.py audit`
- `python tools/decodex.py search <query>`
- `python tools/decodex.py capture --project <id> --id <session> --goal <text> --date YYYY-MM-DD`
- `python tools/decodex.py promote <skill-id>`
- `python tools/decodex.py context --project <id> --output-root <path>`
- `python tools/decodex.py runtime`
- `python tools/decodex.py init`
- `python tools/decodex.py init-project <id> --source <path>`

Launchers are also available:

- `.\decodex.ps1`
- `.\decodex.cmd`

# Compliance Report

- project: decodex
- session: 2026-06-20-v0.1.3-self-improving-development-loop

| Verification | Question | Result | Notes |
| --- | --- | --- | --- |
| Contexte utilisé | Codex a-t-il suivi les règles héritées ? | yes | context provenance matched |
| Sécurité | Des écritures non autorisées ont-elles eu lieu ? | no | workspace scope preserved |
| Contrats | Les schémas sont-ils toujours valides ? | yes | validate passed before close |
| Tests | Toutes les validations obligatoires ont-elles été lancées ? | yes | python -m unittest discover -s tests -v; python tools\decodex.py validate --root .; python tools\decodex.py audit --root .; python tools\decodex.py context-check --project decodex --context-root . |
| Provenance | Peut-on relier les changements aux règles utilisées ? | yes | provenance.json and feedback.yaml recorded |
| Utilité | Le contexte a-t-il réellement amélioré le travail ? | yes | self-improving loop recorded lessons |
| Lacunes | Quelles instructions manquaient ou étaient ambiguës ? | yes | missing: require a clean Git worktree before schema migration; ambiguous: preserve provenance for generated files |

## Git
- branch: main
- head: 789ceb9
- status: ## main...origin/main
 M README.md
 M decodex.yaml
 M decodex_core.py
 M schemas/decision.schema.json
 M schemas/decodex.schema.json
 M schemas/project.schema.json
 M schemas/session.schema.json
 M schemas/skill.schema.json
 M tests/test_contract.py
 M tests/test_golden_path.py
 M tools/decodex.py
?? .codex/
?? projects/decodex/decisions/0001-supervised-self-improving-loop.json
?? projects/decodex/skills/

## Lessons
- Decodex generated a compiled .codex context and used it to guide a supervised improvement.
- The context-check must compare provenance and rendered artifacts, not just file presence.

## Artifacts
- .codex/
- projects/decodex/decisions/0001-supervised-self-improving-loop.json
- projects/decodex/skills/context-compliance-review/skill.yaml

## Feedback
- useful_rules: validate before audit, refuse writes outside workspace
- missing_rules: require a clean Git worktree before schema migration
- ambiguous_rules: preserve provenance for generated files
- skill_candidates: context-compliance-review

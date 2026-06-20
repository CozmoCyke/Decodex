# Changelog

## v0.1.4 — Evidence-Based Skill Lifecycle

Decodex now manages the lifecycle of development skills using traceable evidence rather than relying only on manually assigned status.

### Added

* `skill-eval` for immutable evaluation runs
* `skill-review` for evidence aggregation and cautious recommendations
* `skill-revise` for versioned skill evolution
* `skill-diff` for comparing recorded skill versions
* schemas for skill evaluations, reviews, and revisions
* lifecycle consistency checks in repository audits
* lifecycle metadata in compiled `.codex/` contexts
* CI validation on Windows and Ubuntu

### Improved

* decision discovery supports JSON, YAML, and YML files
* `session-close` no longer overwrites existing skills
* promotion preserves previous versions instead of deleting history
* compiled context includes skill version, status, confidence, latest review, and recommendation

### First evidence-based review

The `context-compliance-review` skill remains deliberately cautious:

* status: `candidate`
* confidence: `low`
* recommendation: `continue_evaluation`

One successful evaluation provides useful evidence, but it is not sufficient for project validation or global promotion.

### Validation

* unit-test suite
* repository schema validation
* repository coherence audit
* compiled-context generation
* context provenance and divergence checks
* Windows and Ubuntu GitHub Actions matrix

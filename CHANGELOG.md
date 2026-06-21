# Changelog

## v0.1.7 -- Global Promotion Readiness

Decodex now records a candidate dossier for global promotion readiness without creating a global skill copy before human review.

### Added

* `skill-promotion-candidate` to package a global-promotion dossier
* `skill-promotion-review` to record the human decision separately
* global promotion readiness in compiled project context
* promotion-candidate schemas and audit checks
* `surepython` as a third real project for evidence aggregation

## v0.1.6 -- Supervised Project Validation

Decodex now supports a supervised project-validation flow for reusable skills. A skill can be evaluated across real projects, reviewed with evidence, approved for project scope by a human, and transitioned without becoming global.

### Added

* `skill-approve` to record immutable project-validation approvals
* `skill-transition` to move a skill into validated project state
* approval schema for supervised validation artifacts
* append-only skill transition history
* lifecycle checks in repository audit
* project-validated context metadata

### Improved

* `context-compliance-review` can now be applied to Decodex itself
* project skills retain human approval provenance
* compiled context distinguishes project validation from global promotion

### Validation

* contract validation
* repository audit
* context generation checks
* project-scoped validation without global publication

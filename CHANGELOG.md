# Changelog

## v0.1.5 — Cross-Project Reuse Proof

Decodex can now apply a validated project skill from one project to another while preserving source provenance, application immutability, and context traceability.

### Added

* `skill-apply` for immutable cross-project skill applications
* `skill-application.schema.json` for application artifacts
* applied project skills in compiled `.codex/` contexts
* provenance checks for application source hashes and session paths
* audit checks for duplicate applications, version mixing, and source hash drift

### Improved

* `skill-review` now aggregates cross-project evidence cautiously
* evaluation artifacts can link back to their application and session
* repository validation covers application artifacts
* project contexts now list applied project skills separately from inherited skills

### Pilot

The `context-compliance-review` skill was applied from `decodex` to `pac-hunt-2` and evaluated against the existing performance report.

The first reuse signal remains cautious:

* status: `candidate`
* confidence: `low`
* recommendation: `continue_evaluation`

Cross-project reuse is now traceable, but still subject to human validation before any broader promotion.

## v0.1.4 — Evidence-Based Skill Lifecycle

Decodex manages skill lifecycle using traceable evidence rather than relying only on manually assigned status.

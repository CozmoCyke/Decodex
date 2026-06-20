# Safe Runtime Modification

## Goal

Modify or install a component without destroying the previous state.

## Procedure

1. Audit the real paths in use.
2. Create a timestamped snapshot.
3. Hash files before modification.
4. Install only the intended files.
5. Compare source and runtime hashes.
6. Run a real functional test.
7. Create an automated rollback path.
8. Produce a validation report.

## Prohibitions

- Never modify a runtime before the snapshot.
- Never treat a copy as valid without comparison.
- Never announce success without a functional test.


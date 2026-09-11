# Architecture

## Authority separation

- **Google Drive** = canonical evidence plane and persistent project storage.
- **GitHub** = source control, review, CI, workflow definitions, and orchestration.
- **Owner Windows x64 laptop** = compute-only execution plane through a self-hosted runner.
- **Colab** = lab/bootstrap/manual fallback.

GitHub is not a second analytical engine. Compute migration must not change frozen parser/routing/delta semantics or behavior-reading methodology.

## Persistent project data

Persistent project data remains in Google Drive. Canonical RAW and governed baseline are read-only during parity. Parity output is written to a separate Drive staging area.

The owner laptop must not retain a permanent full RAW mirror, permanent baseline mirror, persistent parity staging, or governed corpus artifacts.

## Compute-only local working storage

The Windows executor may use bounded ephemeral local scratch only when technically necessary for streaming, SQLite, decompression, or source-scoped processing. Scratch is disposable and non-canonical. Governed artifacts, checkpoints, reconciliation evidence, and PASS/HOLD state must be persisted back to Drive.

## Current migration gate

Windows self-hosted corpus execution is the active compute target, but parity dispatch remains disabled until Drive-aware I/O and bounded local scratch are implemented and validated. The old full-local-path design is superseded.

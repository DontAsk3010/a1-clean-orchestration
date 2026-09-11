# Architecture

## Authority separation

- **Google Drive** = canonical evidence plane and persistent project storage.
- **GitHub** = source control, review, CI, workflow definitions, and orchestration.
- **Remote/cloud compute** = execution plane for corpus processing.
- **Owner Windows laptop** = administration/access endpoint only; not a corpus execution plane.
- **Colab** = lab/bootstrap/manual fallback while migration remains gated.

GitHub is not a second analytical engine. Compute migration must not change frozen parser/routing/delta semantics or behavior-reading methodology.

## Persistent project data

Persistent project data remains in Google Drive. Canonical RAW and governed baseline are read-only during parity. Parity output is written to a separate Drive staging area.

The owner laptop must not retain a full RAW mirror, baseline mirror, persistent parity staging, or corpus-processing artifacts.

## Remote compute working storage

A remote executor may use ephemeral local scratch only when technically necessary for streaming, SQLite, decompression, or source-scoped processing. Ephemeral scratch is disposable and non-canonical. Governed artifacts, checkpoints, reconciliation evidence, and PASS/HOLD state must be persisted back to Drive.

## Current migration gate

Local self-hosted Windows corpus execution is disabled. A remote/cloud compute target and Drive-authenticated I/O path must be established before staging parity is run.

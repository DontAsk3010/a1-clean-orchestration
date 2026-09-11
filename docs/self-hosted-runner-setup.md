# Self-hosted parity runner setup — Windows compute-only

This document defines the owner's Windows x64 workstation as a **compute-only** execution plane. It does not make the laptop a project storage plane.

## Persistent data location

Google Drive is the persistent evidence plane:

- `02_CURRENT_HISTORICAL_RAW_DATA_UJI` — canonical RAW, read-only;
- `UNIVERSAL_BEHAVIOR_DATA_PLANE_CURRENT` — governed baseline, read-only;
- `UNIVERSAL_BEHAVIOR_DATA_PLANE_PARITY_STAGING` — separate parity output/evidence target;
- manifests, checkpoints, reconciliation evidence, and parity reports remain in Drive.

No permanent full corpus, baseline mirror, or parity result may be retained on the owner's laptop.

## Compute role

The Windows x64 laptop may run the GitHub self-hosted runner and execute Python/data-plane work. Local storage is restricted to bounded ephemeral scratch technically required for the currently active source/process, such as SQLite/temp/decompression/streaming state. Scratch is non-canonical and disposable after successful Drive commit/reconciliation.

The design must avoid a permanent full RAW mirror and avoid using local disk as the governed baseline or parity staging root.

## Required runner characteristics

- GitHub self-hosted runner registered to this private repository.
- Windows x64.
- Labels: `self-hosted`, `windows`, `x64`, `a1-clean-parity`.
- Python 3.11+.
- Authenticated Google Drive access with least privilege: RAW/baseline read; parity staging/checkpoint write only where required.
- Bounded local scratch path with sufficient temporary free space for the active source/process.

## Current gate

The old local-filesystem parity workflow remains disabled. Do not dispatch full parity until Drive-aware I/O and bounded scratch behavior are implemented and preflighted. Re-enabling parity must not require permanent local RAW, baseline, or staging directories.

## Safety invariants

- Canonical RAW is never modified by parity.
- Current governed baseline is never a parity write target.
- Parity writes only to the separate Drive staging area.
- Laptop scratch is temporary, non-canonical, and cleanable.
- No formula, threshold, selector, signal, or behavior-reading methodology changes are authorized by compute migration.
- No sampling may be used as final parity evidence.

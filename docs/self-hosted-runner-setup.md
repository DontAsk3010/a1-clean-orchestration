# Execution-plane policy — remote/cloud only

This document supersedes the earlier owner-laptop self-hosted runner setup.

## Owner-machine prohibition

The owner's Windows x64 workstation is **not** an execution plane for A1 CLEAN/QHPX corpus processing. Do not run full parity, delta processing, RAW mirroring, baseline mirroring, persistent staging, pattern-discovery corpus jobs, or production automation on that laptop.

The previously registered Windows self-hosted runner is not part of the governed architecture and must remain stopped/removed.

## Persistent data location

Google Drive is the persistent evidence plane:

- `02_CURRENT_HISTORICAL_RAW_DATA_UJI` — canonical RAW, read-only;
- `UNIVERSAL_BEHAVIOR_DATA_PLANE_CURRENT` — governed baseline, read-only;
- `UNIVERSAL_BEHAVIOR_DATA_PLANE_PARITY_STAGING` — separate parity output/evidence target;
- manifests, checkpoints, reconciliation evidence, and parity reports remain in Drive.

No full corpus, baseline mirror, or parity result is to be retained on the owner's laptop.

## Compute

GitHub remains the control/orchestration plane. A **remote/cloud compute environment** must perform actual corpus processing. The compute target may use its own ephemeral working storage when technically required by Python/SQLite, but that storage is not canonical and must not become a persistent project store. Governed output is committed back to Google Drive.

## Current gate

The local Windows parity workflow has been removed. Do not re-enable parity execution until a remote/cloud compute target and its authenticated Drive I/O path have been selected, configured, and validated without changing frozen V2 semantics.

## Safety invariants

- Canonical RAW is never modified by parity.
- Current governed baseline is never used as parity write target.
- Parity writes only to the separate Drive staging area.
- No formula, threshold, selector, signal, or behavior-reading methodology changes are authorized by compute migration.
- No sampling may be used as final parity evidence.

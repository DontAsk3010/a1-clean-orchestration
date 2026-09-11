# Parity contract

Parity proves that migrated execution preserves the governed V2 data-plane behavior. It does not authorize analytical changes.

## Persistent evidence locations

- Canonical RAW: Google Drive, read-only.
- Governed baseline runtime: Google Drive, read-only.
- Candidate parity output: separate Google Drive staging folder.
- Checkpoints, manifests, reconciliation evidence, and PASS/HOLD records: Google Drive.

The owner Windows laptop is not a parity execution or persistence target.

## Execution plane

Parity must run on a remote/cloud compute target. Ephemeral working storage on that executor is allowed only when technically required by the frozen implementation and must not become canonical storage.

## Required comparisons

Compare stable governed evidence, including source identity/SHA, source and routed row counts, unresolved routing, chronology, ticker-day membership/object counts, physical shard ordering/hashes, semantic JSONL bundle hashes, market-day relationship artifacts, source status/delta classification, and PASS/HOLD behavior.

Normalize only environmental fields such as timestamps, refresh/run identifiers, executor-specific ephemeral paths, and job IDs. Do not accept visual similarity or sampled equivalence as parity.

## Safety

- Never write parity output into `UNIVERSAL_BEHAVIOR_DATA_PLANE_CURRENT`.
- Never mutate canonical RAW.
- Never use sampling as final parity evidence.
- Never change frozen V2 parser/routing/delta constants or semantics to make parity pass.

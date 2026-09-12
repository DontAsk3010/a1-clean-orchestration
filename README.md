# a1-clean-orchestration

Governed A1 CLEAN/QHPX automation and orchestration. The repository now contains the permanent delta-state machine derived from the proven frozen V2 data-plane. Gate F validates that same machine under a SHADOW commit policy; there is no separate throwaway test engine.

Nothing in this repository authorizes formula, score, threshold, selector, optimization, Telegram analytical logic, or behavior-methodology changes.

## Permanent operating architecture

- Google Drive canonical RAW controls source membership dynamically at every governed run.
- Google Drive governed CURRENT is the persistent data-plane state/runtime authority.
- Google Drive PARITY_STAGING stores Gate F checkpoints, processed delta artifacts, control bundles, results, and deployment plans while canonical commit remains locked.
- GitHub is source control, audit trail, and orchestration/control plane.
- Windows self-hosted runner is compute-only; local storage is bounded ephemeral scratch and is not canonical storage.
- Frozen V2 remains the source processor. The automation layer classifies persistent source transitions and routes only required source deltas into that frozen processor.

The source universe is never hard-coded to 17, 18, or any other count. Counts in logs/reports are observations only.

## Permanent governed delta machine

Command:

`a1clean governed-delta --mode SHADOW`

Core modules:

- `src/a1clean/delta_state.py` — deterministic persistent-state classifier for `VERIFIED_UNCHANGED`, `NEW`, `CHANGED`, `REPLACEMENT_SAME_CONTENT`, `REMOVED`, and fail-closed `HOLD` conditions.
- `src/a1clean/delta_artifacts.py` — source-scoped frozen-V2 execution plus governed staging persistence.
- `src/a1clean/delta_control.py` — rebuilds the governed control-state bundle from reused unchanged state plus exact processed-source manifests.
- `src/a1clean/delta_machine.py` — restart-safe permanent orchestration machine, checkpoints, run identity, shadow commit result, and future canonical deployment plan.
- `src/a1clean/source_preflight.py` — dynamic canonical source discovery and exact local identity verification. MD5 and SHA256 are computed in one sequential source read so classification does not require a second full-file hash pass.

Production behavior:

- `VERIFIED_UNCHANGED` → reuse governed artifacts; do not re-run source bytes through frozen V2.
- `NEW` → process full source losslessly through frozen V2.
- `CHANGED` → invalidate/purge prior source-scoped derivative plan and rebuild the source through frozen V2.
- `REPLACEMENT_SAME_CONTENT` → preserve explicit replacement provenance and generate the current source-scoped governed artifacts.
- `REMOVED` → retain canonical RAW authority semantics while the deployment plan removes stale derivatives from active runtime evidence.
- ambiguity, duplicate current content/name, source identity failure, generation/version mismatch, or incomplete dependency → HOLD.

Source-boundary checkpoints are persisted in Drive. A matching rerun resumes from committed source boundaries rather than restarting completed delta work.

## Gate E status

Full dynamic corpus frozen-V2 shadow parity is PASS. The complete canonical universe discovered at that run was reproduced source-by-source with exact governed reconciliation, zero HOLD, and no sampling/filtering/behavior-label creation. The observed count from that run is historical evidence only and not an invariant.

## Gate F status

Gate F is the production-machine activation gate, not a test-engine project.

Workflow:

`Windows Governed Delta Machine`

It is manual-only while Gate F is open, branch-guarded to `migration/parity-v2`, and runs the permanent machine in `SHADOW` mode. The workflow may write only to PARITY_STAGING. Canonical RAW and governed CURRENT remain read-only.

If the canonical source state has not changed since the governed baseline, the machine classifies all sources `VERIFIED_UNCHANGED`, processes zero source bodies through frozen V2, and only builds the next control-state/deployment evidence. If a source is new or changed, only that required delta enters heavy source processing.

The machine also emits a canonical deployment plan describing stale-source purge, processed-source upsert, runtime reconciliation, and control-state replacement order. Gate F records this plan but does not execute it. Canonical commit remains governance-locked until Gate F PASS and explicit owner authorization; activation is a deployment-policy change around the same machine, not an analytical rewrite.

## Governed Drive identities

- canonical RAW: `02_CURRENT_HISTORICAL_RAW_DATA_UJI` / `1gTyt7CzqlubcdZGjWV_lM9Iw8Zg4ib3e`
- governed CURRENT: `UNIVERSAL_BEHAVIOR_DATA_PLANE_CURRENT` / `1SRN-WWkHJefLGLSN6_SktpVU0Ugjwqc-`
- PARITY_STAGING: `UNIVERSAL_BEHAVIOR_DATA_PLANE_PARITY_STAGING` / `1WTb_lGBD6Tuwfcb-1WhsICjyJqzzBtwU`

Credentials remain external to the repository and split by role:

- `A1_DRIVE_READER_CREDENTIALS` — Drive readonly channel for canonical RAW and governed CURRENT.
- `A1_DRIVE_WRITER_CREDENTIALS` — write-capable channel restricted by the migration path to PARITY_STAGING while Gate F is open.

Never commit or paste credential contents, tokens, passwords, or API keys.

## Safety and governance

- no fixed source-count invariant;
- no canonical RAW deletion;
- no canonical CURRENT write while Gate F is open;
- no silent zero substitution or source promotion;
- no sampling/filtering to claim equivalence;
- no behavior labels created by the data-plane automation;
- no analytical formula/signal logic in GitHub orchestration;
- PR #1 remains draft/unmerged until the required production-machine gate passes;
- semantic behavior reading remains a separate governed workstream and is not modified by this automation branch.

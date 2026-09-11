# Self-hosted parity runner setup — Windows-first, Drive-persistent

This is a one-time execution-plane setup. It does not change market methodology.

## Owner execution environment

- GitHub self-hosted runner registered to this private repository.
- Primary owner environment: **Windows x64**.
- Labels required by the parity workflow: `self-hosted`, `windows`, `x64`, `a1-clean-parity`.
- Python 3.11+ available from PowerShell/Command Prompt.

## Storage authority

Persistent A1 CLEAN parity data stays in **Google Drive**, not on the owner's laptop.

Canonical sources remain cloud-side and read-only:

- RAW folder: `02_CURRENT_HISTORICAL_RAW_DATA_UJI`
- Governed baseline runtime: `UNIVERSAL_BEHAVIOR_DATA_PLANE_CURRENT`

Parity output is written only to the separate Drive folder:

- `UNIVERSAL_BEHAVIOR_DATA_PLANE_PARITY_STAGING`
- Drive folder ID: `1WTb_lGBD6Tuwfcb-1WhsICjyJqzzBtwU`

The staging folder is a sibling of the governed current runtime, not a child of it. Never point staging writes at `UNIVERSAL_BEHAVIOR_DATA_PLANE_CURRENT` or the canonical RAW folder.

## Local Windows disk policy

The Windows runner is an **execution plane**, not a persistent evidence store.

- Do not create a permanent full RAW mirror on C: or D:.
- Do not create a permanent full baseline mirror on C: or D:.
- Do not retain parity output on C: or D: after Drive commit.
- Local storage is permitted only for bounded ephemeral scratch required by the running process (for example temporary SQLite, a currently processed file/chunk, or upload staging).
- Ephemeral material must be deleted after successful reconciliation/Drive commit and must not become an alternative canonical source.

This policy is intended to keep the owner's laptop light while preserving the frozen data-plane semantics.

## Drive authentication and permissions

Credentials must never be committed to GitHub or workflow YAML.

The runner must have:

- read access to canonical RAW;
- read access to the governed baseline runtime;
- write access only where required for the dedicated parity-staging folder;
- no parity write path into RAW or the governed current runtime.

Use the least-privilege mechanism available. Authentication setup is operational only and must not change source identity, routing, semantic processing, or parity rules.

## Preflight requirements before a full corpus run

The Drive-only orchestration adapter must verify:

1. Windows runner identity and expected labels.
2. Canonical RAW Drive folder identity.
3. Governed baseline Drive folder identity.
4. Dedicated parity-staging Drive folder identity.
5. RAW/baseline are never selected as write destinations.
6. Staging write access works.
7. Local scratch is ephemeral and separate from canonical/staging identities.
8. Resume/checkpoint state identifies the exact Drive objects already committed.

## Parity sequence

1. Register/configure the Windows x64 self-hosted runner and add label `a1-clean-parity`.
2. Keep the runner online (`Listening for Jobs`).
3. Configure Drive authentication with least privilege.
4. Use the Drive-only adapter to read canonical RAW/baseline and write candidate results to `UNIVERSAL_BEHAVIOR_DATA_PLANE_PARITY_STAGING`.
5. Use only bounded ephemeral local scratch during processing.
6. Reconcile candidate artifacts against the governed baseline.
7. Delete/release ephemeral local material after successful Drive commit/reconciliation.
8. Do not merge/enable canonical automation unless the parity comparator passes.

The previous local-full-mirror design is superseded. Linux is not the default owner environment for this project; it may be evaluated later only as an optional server/cloud execution target for a concrete operational reason.

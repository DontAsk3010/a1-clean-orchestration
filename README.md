# a1-clean-orchestration

Governed migration of the proven A1 CLEAN/QHPX Colab data-plane to reusable Python + GitHub orchestration + remote/cloud compute.

Current branch goal: **parity first**. Nothing in this repository authorizes formula, score, threshold, selector, Telegram analytical logic, or behavior-methodology changes.

## Components

- `src/a1clean/frozen_v2.py` — mechanical V2 parity anchor from the governed notebook.
- `a1clean delta` — executes the frozen engine against the configured runtime root.
- `a1clean parity BASELINE CANDIDATE` — compares governed baseline vs staging artifacts.
- `checkpoint.py` — operational restart state.
- `pattern_discovery/` — isolated Ruptures/STUMPY/DTW-tslearn wrappers with no project analytical defaults.
- `.github/workflows/ci.yml` — lightweight GitHub-hosted tests only.

## Execution policy

The owner's Windows laptop is **not** an execution plane for project corpus processing. Do not run parity, delta processing, RAW mirroring, baseline mirroring, or persistent staging on the owner laptop.

Google Drive remains the persistent evidence plane:

- canonical RAW: read-only;
- governed baseline runtime: read-only;
- parity staging/evidence: separate Google Drive folder;
- manifests/checkpoints/evidence: Google Drive.

A remote/cloud compute target must be selected and configured before parity execution is re-enabled. Local files on the owner laptop are not part of the governed parity architecture.

## Safety

Parity output must never target `UNIVERSAL_BEHAVIOR_DATA_PLANE_CURRENT`. Canonical RAW remains read-only. The former Windows self-hosted parity workflow was removed so an Actions dispatch cannot route corpus processing to the owner's laptop.

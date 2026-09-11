# a1-clean-orchestration

Governed migration of the proven A1 CLEAN/QHPX Colab data-plane to reusable Python + GitHub orchestration + a Windows self-hosted compute runner.

Current branch goal: **parity first**. Nothing in this repository authorizes formula, score, threshold, selector, Telegram analytical logic, or behavior-methodology changes.

## Components

- `src/a1clean/frozen_v2.py` — mechanical V2 parity anchor from the governed notebook.
- `a1clean delta` — executes the frozen engine against the configured runtime root.
- `a1clean parity BASELINE CANDIDATE` — compares governed baseline vs staging artifacts.
- `checkpoint.py` — operational restart state.
- `pattern_discovery/` — isolated Ruptures/STUMPY/DTW-tslearn wrappers with no project analytical defaults.
- `.github/workflows/ci.yml` — lightweight GitHub-hosted tests only.

## Execution policy

The owner's Windows x64 laptop may be used as a **compute-only self-hosted runner** for parity and later governed corpus processing.

Google Drive remains the persistent evidence plane:

- canonical RAW: read-only;
- governed baseline runtime: read-only;
- parity staging/evidence: separate Google Drive folder;
- manifests/checkpoints/reconciliation evidence: Google Drive.

The laptop must not become persistent project storage. No permanent full RAW mirror, permanent baseline mirror, or retained parity corpus is allowed locally. Executor-local files are limited to bounded ephemeral scratch required by Python/SQLite/source-scoped processing and must be disposable after governed Drive commit/reconciliation.

## Dynamic source universe

The governed RAW universe is discovered dynamically from the canonical Google Drive RAW folder at run time. It must never be hard-coded to a fixed source count. Any source count displayed in logs or reports is observational only.

Canonical Drive controls membership. Local RAW files are read-only compute-side copies/cache. Missing local counterparts, duplicate canonical filenames, size mismatches, or checksum mismatches must HOLD rather than silently continue.

## Current governed baseline candidate

The latest completed Colab refresh has been verified from Drive. `Raw Maret 03-31-2025.csv` was accepted as `NEW_PROCESSED`; all currently discovered canonical sources are `ACCESS_READY_FOR_AI`; latest holds are empty; changed/removed are zero; unresolved routing remains zero; and the delta semantic gate is `READY_FOR_AI_DELTA`.

This is a data-plane baseline candidate for parity only. It is **not** a behavior-semantic research PASS: the notebook still reports semantic reader `NOT_RUN_BY_THIS_NOTEBOOK` and behavior-event-journey `NOT_EVALUATED_BY_THIS_NOTEBOOK`.

## Current gate

The former local-path parity workflow remains disabled until Drive-persistent output/checkpoint I/O and bounded local scratch are fully validated. Do not re-enable parity by pointing the frozen engine at permanent local RAW/baseline/staging folders.

Next implementation gate: finish Drive-aware I/O, run source-preflight against the dynamic canonical universe, validate read-baseline/write-staging separation, then perform full staging parity against `UNIVERSAL_BEHAVIOR_DATA_PLANE_PARITY_STAGING`.

## Safety

Parity output must never target `UNIVERSAL_BEHAVIOR_DATA_PLANE_CURRENT`. Canonical RAW remains read-only. No formula, threshold, selector, signal, or behavior-reading methodology changes are authorized by execution migration. PR #1 must remain unmerged until parity PASS.

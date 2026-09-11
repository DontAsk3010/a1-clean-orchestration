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

## Current gate

The former local-path parity workflow remains disabled until Drive-persistent I/O and bounded local scratch are implemented and validated. Do not re-enable parity by pointing the frozen engine at permanent local RAW/baseline/staging folders.

## Safety

Parity output must never target `UNIVERSAL_BEHAVIOR_DATA_PLANE_CURRENT`. Canonical RAW remains read-only. No formula, threshold, selector, signal, or behavior-reading methodology changes are authorized by execution migration.

# a1-clean-orchestration

Governed migration of the proven A1 CLEAN/QHPX Colab data-plane to reusable Python + GitHub orchestration + a Windows self-hosted compute runner.

Current branch goal: **parity first**. Nothing in this repository authorizes formula, score, threshold, selector, Telegram analytical logic, or behavior-methodology changes.

## Components

- `src/a1clean/frozen_v2.py` — mechanical V2 parity anchor from the governed notebook.
- `a1clean delta` — executes the frozen engine against the configured runtime root.
- `a1clean source-preflight` — discovers the current canonical RAW universe from Google Drive and verifies matching local read-only files.
- `a1clean parity BASELINE CANDIDATE` — compares governed baseline vs staging artifacts.
- `checkpoint.py` — operational restart state.
- `pattern_discovery/` — isolated Ruptures/STUMPY/DTW-tslearn wrappers with no project analytical defaults.
- `.github/workflows/ci.yml` — lightweight GitHub-hosted tests only.

## Dynamic source universe

The RAW source universe is **never hard-coded to a fixed file count**. No governed logic may assume 17, 18, or any other constant number of source files.

At each preflight/run, the required universe is discovered from all valid source files currently present in the canonical Google Drive RAW folder. Reported source counts are observations only. If the canonical folder gains or loses a governed source, discovery must reflect that current state automatically without changing analytical methodology or editing a fixed count in code.

Canonical Drive controls source membership. The local Windows RAW folder is only a read-only compute-side copy/cache and must not promote extra local files into the governed universe automatically.

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

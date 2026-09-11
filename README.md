# a1-clean-orchestration

Governed migration of the proven A1 CLEAN/QHPX Colab data-plane to reusable Python + GitHub orchestration + a Windows self-hosted compute runner.

Current branch goal: **parity first**. Nothing in this repository authorizes formula, score, threshold, selector, Telegram analytical logic, or behavior-methodology changes.

## Components

- `src/a1clean/frozen_v2.py` — mechanical V2 parity anchor from the governed notebook.
- `a1clean delta` — executes the frozen engine against the configured runtime root.
- `a1clean parity BASELINE CANDIDATE` — compares governed baseline vs staging artifacts.
- `a1clean drive-preflight` — validates governed Drive folder identity/permission separation and performs one tiny create/delete probe in parity staging only.
- `a1clean source-preflight` — dynamically discovers the canonical Drive RAW universe and reconciles it against the local read-only RAW copy by exact name/size/checksum.
- `checkpoint.py` — operational restart state.
- `pattern_discovery/` — isolated Ruptures/STUMPY/DTW-tslearn wrappers with no project analytical defaults.
- `.github/workflows/ci.yml` — lightweight GitHub-hosted tests only.
- `.github/workflows/windows-runner-smoke.yml` — compute-endpoint smoke test only.
- `.github/workflows/windows-drive-guardrail-preflight.yml` — manual-only Drive guardrail/source-identity preflight; it never runs automatically on PR/push.

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

## Governed Drive identities

Current frozen migration bindings:

- canonical RAW folder: `02_CURRENT_HISTORICAL_RAW_DATA_UJI` / `1gTyt7CzqlubcdZGjWV_lM9Iw8Zg4ib3e`;
- governed baseline runtime: `UNIVERSAL_BEHAVIOR_DATA_PLANE_CURRENT` / `1SRN-WWkHJefLGLSN6_SktpVU0Ugjwqc-`;
- parity staging: `UNIVERSAL_BEHAVIOR_DATA_PLANE_PARITY_STAGING` / `1WTb_lGBD6Tuwfcb-1WhsICjyJqzzBtwU`.

Drive credentials are external to the repository and split by role:

- `A1_DRIVE_READER_CREDENTIALS` — reader identity used only for canonical RAW and governed CURRENT; those folders must be non-editable to this identity.
- `A1_DRIVE_WRITER_CREDENTIALS` — writer identity used only for PARITY_STAGING.

Each credential file may be an `authorized_user` OAuth credential JSON or a service-account credential JSON. `A1_GOOGLE_APPLICATION_CREDENTIALS` remains a compatibility fallback only. Secrets must never be committed to GitHub or pasted into project documentation/chat.

`drive-preflight` is deliberately fail-closed: the three governed folder identities must match and be distinct; canonical RAW and governed CURRENT must be read-only through the reader identity; parity staging must be writable through the separate writer identity. Only after those gates pass does the preflight create and immediately delete one tiny probe object in parity staging.

Because PARITY_STAGING is currently in My Drive, service-account-only staging writes are not assumed. Google documents that service accounts do not have storage quota and should use shared drives or OAuth on behalf of a human user for Drive uploads. The writer channel therefore remains credential-agnostic and must be validated by the live guardrail before any parity output is allowed.

## Current governed baseline candidate

The latest completed Colab refresh has been verified from Drive. `Raw Maret 03-31-2025.csv` was accepted as `NEW_PROCESSED`; all currently discovered canonical sources are `ACCESS_READY_FOR_AI`; latest holds are empty; changed/removed are zero; unresolved routing remains zero; and the delta semantic gate is `READY_FOR_AI_DELTA`.

This is a data-plane baseline candidate for parity only. It is **not** a behavior-semantic research PASS: the notebook still reports semantic reader `NOT_RUN_BY_THIS_NOTEBOOK` and behavior-event-journey `NOT_EVALUATED_BY_THIS_NOTEBOOK`.

## Current gate

Windows runner connectivity is proven. The compute-only smoke workflow passes Windows/X64, Python 3.11+, and local RAW readability.

Drive guardrail code and unit tests are installed on `migration/parity-v2`. The live Drive preflight is intentionally **not yet dispatched** until separate reader/writer credential bindings are present and the intended RAW-read/CURRENT-read/STAGING-write separation is proven.

After Drive guardrail PASS, run source-preflight against the dynamically discovered canonical universe. Only then may source-scoped staging parity be opened. The former local-path parity workflow remains disabled.

## Safety

Parity output must never target `UNIVERSAL_BEHAVIOR_DATA_PLANE_CURRENT`. Canonical RAW remains read-only. No formula, threshold, selector, signal, or behavior-reading methodology changes are authorized by execution migration. PR #1 must remain unmerged until parity PASS.

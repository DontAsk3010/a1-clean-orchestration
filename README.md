# a1-clean-orchestration

Governed migration of the proven A1 CLEAN/QHPX Colab data-plane to reusable Python + GitHub orchestration + a Windows self-hosted compute runner.

Current branch goal: **parity first**. Nothing in this repository authorizes formula, score, threshold, selector, Telegram analytical logic, or behavior-methodology changes.

## Components

- `src/a1clean/frozen_v2.py` — mechanical V2 parity anchor from the governed notebook.
- `a1clean delta` — executes the frozen engine against the configured runtime root.
- `a1clean parity BASELINE CANDIDATE` — compares governed baseline vs staging artifacts.
- `a1clean drive-preflight` — validates governed Drive folder identity/access separation; proves the readonly reader cannot write and proves the writer can create/delete one tiny object in parity staging.
- `a1clean source-preflight` — dynamically discovers the canonical Drive RAW universe and reconciles it against the local read-only RAW copy by exact name/size/checksum.
- `a1clean source-parity --source-name ...` — one-source frozen-V2 Windows parity technical gate against the governed Drive baseline. It is not full-corpus parity evidence.
- `checkpoint.py` — operational restart state.
- `pattern_discovery/` — isolated Ruptures/STUMPY/DTW-tslearn wrappers with no project analytical defaults.
- `.github/workflows/ci.yml` — lightweight GitHub-hosted tests only.
- `.github/workflows/windows-runner-smoke.yml` — compute-endpoint smoke test only.
- `.github/workflows/windows-drive-guardrail-preflight.yml` — manual-only Drive guardrail/source-identity preflight; it never runs automatically on PR/push.
- `.github/workflows/windows-source-parity.yml` — manual-only one-source parity technical gate. It re-runs Drive/source preflights before frozen-V2 execution.

## Execution policy

The owner's Windows x64 laptop may be used as a **compute-only self-hosted runner** for parity and later governed corpus processing.

Google Drive remains the persistent evidence plane:

- canonical RAW: read-only;
- governed baseline runtime: read-only;
- parity staging/evidence: separate Google Drive folder;
- manifests/checkpoints/reconciliation evidence: Google Drive.

The laptop must not become persistent project storage. No permanent full RAW mirror, permanent baseline mirror, or retained parity corpus is allowed locally. Executor-local files are limited to bounded ephemeral scratch required by Python/SQLite/source-scoped processing and must be disposable after governed Drive reconciliation/evidence commit.

## Dynamic source universe

The governed RAW universe is discovered dynamically from the canonical Google Drive RAW folder at run time. It must never be hard-coded to a fixed source count. Any source count displayed in logs or reports is observational only.

Canonical Drive controls membership. Local RAW files are read-only compute-side copies/cache. Missing local counterparts, duplicate canonical filenames, size mismatches, or checksum mismatches must HOLD rather than silently continue.

A source-scoped parity run deliberately selects one already-verified canonical source only as a **technical migration gate**. That selection is not sampling evidence, does not redefine the canonical universe, and cannot establish full-corpus parity.

## Governed Drive identities

Current frozen migration bindings:

- canonical RAW folder: `02_CURRENT_HISTORICAL_RAW_DATA_UJI` / `1gTyt7CzqlubcdZGjWV_lM9Iw8Zg4ib3e`;
- governed baseline runtime: `UNIVERSAL_BEHAVIOR_DATA_PLANE_CURRENT` / `1SRN-WWkHJefLGLSN6_SktpVU0Ugjwqc-`;
- parity staging: `UNIVERSAL_BEHAVIOR_DATA_PLANE_PARITY_STAGING` / `1WTb_lGBD6Tuwfcb-1WhsICjyJqzzBtwU`.

Drive credentials are external to the repository and split by role:

- `A1_DRIVE_READER_CREDENTIALS` — reader credential used for canonical RAW and governed CURRENT through Drive readonly OAuth scope.
- `A1_DRIVE_WRITER_CREDENTIALS` — writer credential used only for PARITY_STAGING through write-capable Drive scope.

Each credential file may be an `authorized_user` OAuth credential JSON or a service-account credential JSON. `A1_GOOGLE_APPLICATION_CREDENTIALS` remains a compatibility fallback only. Secrets must never be committed to GitHub or pasted into project documentation/chat.

Google Drive `capabilities` describe resource/ACL capability and can therefore show owner/editor rights even when the active OAuth token is readonly. The governed live guardrail does not treat those ACL flags as proof that the reader token can write. Effective separation is proven by a safe attempted create in `PARITY_STAGING`: the reader must be denied, while the writer must successfully create and immediately delete its tiny probe. No write probe is ever directed at canonical RAW or governed CURRENT.

Because PARITY_STAGING is currently in My Drive, service-account-only staging writes are not assumed. The writer channel remains credential-agnostic and must pass the live guardrail before any parity evidence write is allowed.

## Current governed baseline candidate

The latest completed Colab refresh has been verified from Drive. `Raw Maret 03-31-2025.csv` was accepted as `NEW_PROCESSED`; all currently discovered canonical sources are `ACCESS_READY_FOR_AI`; latest holds are empty; changed/removed are zero; unresolved routing remains zero; and the delta semantic gate is `READY_FOR_AI_DELTA`.

This is a data-plane baseline candidate for parity only. It is **not** a behavior-semantic research PASS: the notebook still reports semantic reader `NOT_RUN_BY_THIS_NOTEBOOK` and behavior-event-journey `NOT_EVALUATED_BY_THIS_NOTEBOOK`.

## Current gate

Windows runner connectivity is proven. The compute-only smoke workflow passes Windows/X64, Python 3.11+, and local RAW readability.

The live Drive guardrail has PASS evidence: the readonly reader was denied a safe staging create with HTTP 403; the writer successfully created and deleted its tiny staging probe. The subsequent dynamic full source-identity reconciliation also PASSed: every source then discovered in canonical Drive matched the local read-only compute copy by exact name, size, and MD5, with no extra local files or duplicate canonical names. The observed source count from that run is evidence only and is never a fixed universe limit.

The next migration gate is **source-scoped frozen-V2 parity**. `.github/workflows/windows-source-parity.yml` is manual-only and re-runs the live Drive guardrail plus the complete dynamic source-preflight before executing one selected canonical source. Candidate physical shards and semantic bundles are compared byte-for-byte by MD5 against the governed CURRENT baseline; stable source/global manifest fields, semantic bundle manifest, and market-day index are also reconciled. Only reconciliation evidence/manifests are persisted to PARITY_STAGING for this one-source technical gate, and local candidate/scratch is removed afterward.

A source-scoped PASS does not equal full-corpus parity. Full dynamically discovered corpus shadow parity and delta-state parity remain required before PR #1 may be considered for merge or canonical automated delta may be enabled.

## Safety

Parity evidence/output must never target `UNIVERSAL_BEHAVIOR_DATA_PLANE_CURRENT`. Canonical RAW remains read-only. No formula, threshold, selector, signal, or behavior-reading methodology changes are authorized by execution migration. PR #1 must remain unmerged until the required parity gates PASS.

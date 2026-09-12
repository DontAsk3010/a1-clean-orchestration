# a1-clean-orchestration

Permanent governed automation/orchestration for A1 CLEAN/QHPX. This repository contains one durable production machine; SHADOW, readback, promotion, activation, and watch modes are safety/commit modes around the same system, not throwaway alternate engines.

Nothing here authorizes formula, score, threshold, selector, optimization, Telegram analytical logic, or behavior-methodology changes.

## Authority and execution

- Google Drive canonical RAW controls source membership dynamically.
- Google Drive governed CURRENT is the persistent data-plane/control authority.
- Google Drive behavior-control state stores independent semantic research continuity.
- PARITY_STAGING stores checkpoints, reconciliation, rollback, and audit evidence.
- GitHub is source control, CI, workflow definition, audit trail, and orchestration.
- Windows self-hosted runner is compute-only; bounded local scratch is non-canonical.
- Frozen V2 remains the source processor.

No source count is hard-coded. Counts in logs/reports are observations only.

## Permanent governed machine

The machine supports dynamic discovery, exact source identity, persistent state, restart-safe checkpoints, exact resume, delta-only source processing, reconciliation before commit, rollback/recovery evidence, semantic work-state continuity, canonical conditional promotion, and PASS/HOLD reporting.

Data-plane transitions:

- `VERIFIED_UNCHANGED` -> reuse governed artifacts; no source-body rebuild.
- `NEW` -> full lossless frozen-V2 processing.
- `CHANGED` -> invalidate affected derivative scope and rebuild that source.
- `REPLACEMENT_SAME_CONTENT` -> preserve replacement provenance.
- `REMOVED` -> remove stale active derivatives; canonical RAW is never deleted by automation.
- ambiguity/duplicate/identity/dependency failure -> fail-closed `HOLD`.

## Dual-state semantic continuity

Data-plane state and semantic-research completion are independent. `VERIFIED_UNCHANGED` never means behavior research is complete.

The permanent machine maintains:

- `PERSISTENT_SEMANTIC_RESEARCH_STATE.json`
- `AI_SEMANTIC_WORK_QUEUE.json`

An unchanged source with unfinished semantic work resumes from its exact semantic checkpoint without rebuilding unchanged data-plane artifacts. Semantic research is not a live-trading dependency.

## Canonical promotion and activation

Gate G canonical promotion and Gate H activation have runtime PASS evidence. The production activation path now proves material NOOP behavior: if neither source state nor semantic checkpoint state materially changed, canonical state is not rewritten.

The same activation path performs conditional canonical promotion only after exact hashing/classification/reconciliation admits it. Canonical RAW remains never-written.

## Governed unattended trigger

Production trigger policy is `HOURLY_LIGHTWEIGHT_WATCH` once the workflow is present on the default `main` branch.

Schedule:

`17 * * * *`

This hourly schedule is for historical/backfill RAW and semantic-checkpoint continuity. It is **not** the HPX/AmiBroker live-trading clock.

The scheduled path is deliberately two-tiered:

1. lightweight Drive metadata watch checks canonical RAW membership/metadata and governed semantic checkpoint metadata;
2. only when material drift is detected does it admit the existing permanent activation path, which performs exact local hashing, data-plane classification, reconciliation, conditional canonical promotion, and post-commit readback.

When nothing material changed, the watch performs no local corpus hashing, no heavy data-plane processing, and no canonical write. Manual workflow dispatch remains an operational fallback.

## Live trading boundary

Future live trading must remain deterministic and independent from AI semantic reading. First analytical production candidate remains:

`HPX/QHPX -> AmiBroker/AFL governed engine -> optional thin Python bridge/logging/retry/health -> Telegram`

Python must not silently become a second analytical engine. Telegram remains transport/presentation only.

## Governed Drive identities

- canonical RAW: `02_CURRENT_HISTORICAL_RAW_DATA_UJI` / `1gTyt7CzqlubcdZGjWV_lM9Iw8Zg4ib3e`
- governed CURRENT: `UNIVERSAL_BEHAVIOR_DATA_PLANE_CURRENT` / `1SRN-WWkHJefLGLSN6_SktpVU0Ugjwqc-`
- PARITY_STAGING: `UNIVERSAL_BEHAVIOR_DATA_PLANE_PARITY_STAGING` / `1WTb_lGBD6Tuwfcb-1WhsICjyJqzzBtwU`

Credentials remain external to the repository and split by role. Never commit or paste credential contents, tokens, passwords, or API keys.

## Safety invariants

- no fixed source-count invariant;
- RAW never written/deleted by automation;
- no silent zero substitution/source promotion;
- no sampling/filtering to claim equivalence;
- no behavior labels created by the data-plane automation;
- no formula/signal logic in GitHub orchestration;
- material no-change must remain a true NOOP;
- scheduled polling must remain lightweight unless a material change admits the heavy production path;
- semantic backlog is research continuity state, not live-signal freshness;
- fail closed on identity/access/reconciliation mismatch.

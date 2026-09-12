# Architecture

## Authority separation

- **Google Drive** = canonical evidence plane and persistent project state.
- **GitHub** = source control, review, CI, workflow definitions, audit trail, and orchestration.
- **Windows x64 self-hosted runner** = compute-only execution plane; local scratch is bounded and non-canonical.
- **Colab** = lab/bootstrap/manual fallback, not the production operating system.
- **AI semantic reader** = research/validation/behavior-atlas lane, not a live trading dependency.

GitHub is not a second analytical engine. Automation must not change frozen parser/routing/data-plane semantics or behavior-reading methodology.

## Delivery discipline — success path, not a sandbox

The repository converges on one durable governed operating system. Every change must advance the current authorized gate, repair an observed production-path blocker, or harden an already governed production requirement. SHADOW/parity/readback/NOOP verification uses the same production modules rather than a disposable implementation.

A PASSed gate is not reopened merely to try alternatives. Reopen requires actual new evidence, a dependency/authority change, an observed defect, or explicit owner instruction.

## Permanent machine

One machine owns:

`canonical discovery -> exact identity -> delta classification -> source-scoped processing -> reconciliation -> persistent controls -> semantic work-state continuity -> canonical conditional promotion -> post-commit readback -> PASS/HOLD`

Data transitions remain `VERIFIED_UNCHANGED`, `NEW`, `CHANGED`, `REPLACEMENT_SAME_CONTENT`, `REMOVED`, and fail-closed `HOLD`. Source membership is always discovered dynamically; source count is never an invariant.

## Permanent dual-state rule

DATA-PLANE state and SEMANTIC-RESEARCH state are independent. `VERIFIED_UNCHANGED` means source/data-plane derivatives do not require rebuild; it never means behavior research is complete.

The semantic ledger/work queue preserves unfinished source/date/ticker scope, OPEN carry, reconciliation obligations, and exact resume points without forcing unchanged data-plane artifacts through frozen V2 again.

Semantic orchestration creates no behavior label, score, threshold, selector, signal, or trading decision.

## Canonical promotion and activation

Canonical promotion is a guarded commit policy of the same permanent machine. RAW is never a write target. A promotion transaction requires reconciled source/control state, explicit authorization, source-scoped backup/purge/upsert when a real delta exists, exact post-write readback, and rollback evidence on failure.

The production activation cycle consumes canonical state, re-enters the permanent machine, conditionally promotes only material changes, then performs governed post-commit readback. Material no-change is a real NOOP: volatile timestamps/run IDs do not create canonical rewrite loops.

## Governed unattended trigger

The operational control-plane trigger is `HOURLY_LIGHTWEIGHT_WATCH` after promotion to the default `main` branch. Schedule is `17 * * * *`.

This is intentionally **not** an hourly execution of the heavy corpus path. It is a two-tier admission architecture:

`hourly lightweight Drive metadata watch`

`-> no material RAW/checkpoint drift: stop as NOOP`

`-> material drift: admit the existing permanent exact activation path`

The watch compares canonical RAW membership/size/modified metadata and semantic CURRENT-checkpoint metadata against governed canonical state. It does not hash the local corpus and does not mutate canonical state. Missing/ambiguous metadata becomes an activation hint so the exact production path can verify or HOLD; the watch never promotes evidence by itself.

Only an admitted activation performs the expensive steps: local MD5+SHA256 verification, persistent delta classification, source processing when required, semantic control refresh, reconciliation, conditional canonical promotion, and post-commit readback.

Manual dispatch remains fallback. Concurrency is serialized; scheduled runs do not cancel an in-progress governed run.

This hourly policy is designed for historical/backfill RAW and research-control continuity. It is not the future realtime HPX/AmiBroker signal clock.

## Live trading execution rule — no AI in the latency-critical path

Future live trading remains deterministic and independent from AI semantic completion. Preferred initial topology:

`HPX/QHPX -> AmiBroker/AFL canonical deterministic engine -> optional thin Python bridge/logging/retry/health -> Telegram`

A Python analytical engine may only become authoritative after a later governed parity/admission gate proves equivalent or superior behavior on the same market evidence. Programming language itself does not determine accuracy.

Telegram is transport/presentation only and must not calculate independent thresholds, targets, rankings, or analytical conclusions.

## Live-route admission criteria

Any future analytical route change must be proven on the same recorded-live/live evidence for provider-field semantics, timestamps/order, session boundaries, duplicates/missing/late/stale/reconnect handling, canonical-state equivalence, formula/output parity, latency/jitter, restart/recovery continuity, and end-to-end provenance.

This is separate from the historical/backfill GitHub schedule.

## AI future role

AI is valid for research/testing behavior-event-journey reading and later may prepare supplementary issuer/company/external-market/news context for Telegram. That supplementary lane is non-authoritative unless separately admitted by Master authority and must preserve publication/known-at time.

## Persistent project data

Persistent RAW, governed runtime, controls, checkpoints, reconciliation evidence, rollback evidence, and PASS/HOLD state remain in Google Drive. The Windows executor must not become canonical storage for corpus mirrors.

## Gate progression rule

`authorized gate -> durable production implementation -> persisted runtime/readback evidence -> PASS/HOLD -> repair only observed blocker -> close gate -> next authorized gate`

Code existing or CI green alone does not close a runtime gate. Conversely, once runtime/readback acceptance has PASSed, the gate is closed rather than kept as an experimentation area.

## Current engineering state

The following are CLOSED/PASS on the permanent path:

- full dynamic corpus frozen-V2 shadow parity;
- permanent governed delta-machine SHADOW baseline;
- dual-state semantic ledger/work scheduler runtime;
- canonical promotion transaction/readback;
- post-commit automation activation;
- material-no-change NOOP behavior.

The unattended trigger implementation adds the lightweight hourly admission layer without introducing a second engine or live-trading dependency. Promotion to `main` is what activates the GitHub schedule. Formula/model/signal work and HPX/AmiBroker live deployment remain separate future authority gates.

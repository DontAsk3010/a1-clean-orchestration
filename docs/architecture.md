# Architecture

## Authority separation

- **Google Drive** = canonical evidence plane and persistent project storage.
- **GitHub** = source control, review, CI, workflow definitions, audit trail, and orchestration.
- **Owner Windows x64 environment** = compute/execution plane when authorized; persistent governed evidence remains in Drive.
- **Colab** = lab/bootstrap/manual fallback, not the target operating system.
- **AI semantic reader** = research/validation/behavior-atlas lane, not a live trading execution dependency.

GitHub is not a second analytical engine. Compute migration and automation work must not change frozen parser/routing/delta semantics or behavior-reading methodology.

## Delivery discipline — success path, not a sandbox

This repository is built to converge on one durable governed operating system. It is not a place for open-ended experimentation, parallel prototype engines, or permanent test-only implementations.

Every repository change must satisfy at least one of these conditions:

1. advance the current explicitly authorized gate toward its acceptance criteria;
2. repair a blocker observed by that gate without widening analytical scope; or
3. harden a production requirement already owned by current authority, such as restart safety, reconciliation, provenance, access separation, or recovery.

Verification remains mandatory, but parity, shadow, dry-run, and validation must exercise the same production modules, state model, Drive I/O contract, checkpoint/recovery path, and reconciliation gates intended for governed operation. A test-only alternate engine is not an acceptable primary deliverable.

Once an exact audited gate has PASSed, do not reopen or redesign it merely to try another implementation. Reopen only when new evidence, a changed dependency, an actual defect, or an explicit owner instruction requires it. Optional tooling, infrastructure alternatives, algorithmic-discovery expansion, external-news AI, participant-flow extensions, formula/model work, scheduling, and live deployment are not pulled into the current gate unless the governing authority explicitly makes them necessary.

## Permanent dual-state rule

DATA-PLANE state and SEMANTIC-RESEARCH work state are independent.

`VERIFIED_UNCHANGED` means source/data-plane bytes and governed derivatives do not require rebuild. It never means AI behavior research is complete. The permanent machine emits a separate semantic research ledger and authoritative semantic work queue so unfinished historical/replay research can resume from its exact checkpoint without rebuilding unchanged data-plane artifacts.

The semantic ledger/scheduler performs orchestration only. It creates no behavior labels, formula, score, threshold, selector, signal, or trading decision.

## Live trading execution rule — no AI in the latency-critical path

Future live trading is deterministic. AI must not sit between HPX/QHPX market data and the governed live trading result, and live operation must not wait for AI to finish reading each second.

Target live topology is selected from deterministic implementations such as:

`HPX/QHPX -> AmiBroker governed engine -> Telegram transport`

or, only when technically justified and governed parity proves equivalence:

`HPX/QHPX -> deterministic Python governed engine/bridge -> Telegram transport`

A hybrid is allowed and is the first operational preference when AmiBroker remains the canonical analytical engine while Python handles non-analytical transport, persistence, logging, health, retry, and Telegram delivery:

`HPX/QHPX -> AmiBroker canonical deterministic state -> thin Python bridge/logging -> Telegram`

Python must not silently become a second analytical engine. If analytical execution is ever moved from AFL/AmiBroker to Python, the Python implementation requires explicit governed parity against the canonical formula/state semantics before it may become authoritative.

## Live-path selection criterion

Programming language does not determine trading accuracy. The authoritative route must be chosen from measured evidence, not preference. If a Python analytical route is proposed later, compare it against the incumbent canonical path on the same recorded-live/replay source and require equivalence for:

- source field semantics and entitlement/availability states;
- event/tick/bar timestamp ordering and session boundaries;
- duplicate, missing, late, stale, and reconnect handling;
- canonical current-state outputs for every eligible ticker;
- deterministic formula outputs from identical inputs;
- end-to-end latency and jitter;
- restart/recovery behavior and state continuity;
- replay versus live/recorded-live parity;
- audit provenance from HPX/QHPX input to Telegram output.

This comparison is a governed admission gate, not an invitation to maintain two competing analytical engines. Until evidence proves otherwise, prefer the shortest validated path with the fewest transformations between the HPX/QHPX feed and the canonical deterministic analytical engine. Because the current market-data/replay environment is already HPX/QHPX-linked to AmiBroker, AmiBroker should remain the first production analytical candidate; Python is initially a thin operational bridge unless a later parity gate proves a Python analytical path superior or necessary.

Telegram is presentation/transport only. It must not calculate independent thresholds, targets, rankings, or analytical conclusions.

## AI future role

AI may be used during research/testing to read behavior/event/journey evidence, reconcile pattern families, and help build the Behavior Atlas before narrative-to-deterministic translation is authorized.

Later, AI may also prepare **supplementary** external information such as issuer/company context, disclosures, market context, and news updates for Telegram. That lane is outside the current implementation scope. Such information remains supplementary unless the governing Master explicitly authorizes it as an analytical input. It must preserve publication/known-at time so later information cannot be backdated into an earlier trading decision.

## Realtime research continuity

Even after live trading begins, historical/shadow-live/recorded-live research may continue asynchronously. Capture state, deterministic current market state, semantic research state, and post-session/EOD reconciliation remain separate. Semantic backlog never changes the live formula result and does not block authorized lossless market capture merely because AI research is behind.

## Persistent project data

Persistent project data remains in Google Drive. Canonical RAW and governed runtime targets are protected by the active commit policy. Shadow/parity output is written to a separate Drive staging area.

The owner laptop must not become canonical persistent storage for full RAW mirrors, baseline mirrors, or governed corpus artifacts. Bounded ephemeral scratch is permitted when technically required by the active source/job.

## Compute-only local working storage

The Windows executor may use bounded ephemeral local scratch only when technically necessary for streaming, SQLite, decompression, or source-scoped processing. Scratch is disposable and non-canonical. Governed artifacts, checkpoints, reconciliation evidence, and PASS/HOLD state must be persisted to the governed evidence plane.

## Gate progression rule

The engineering path is linear and evidence-gated:

`current authorized gate -> production-path implementation -> persisted verification evidence -> PASS/HOLD -> repair only observed blocker if HOLD -> close gate -> next explicitly authorized gate`

A gate is not complete because code exists or CI is green. It closes only when its required runtime/readback/reconciliation evidence passes. Conversely, a completed gate is not kept open as a permanent experimentation area.

## Current engineering state

Full dynamic corpus frozen-V2 shadow parity has PASSed. The permanent governed delta machine has also PASSed its observed no-change SHADOW path. The same production machine now contains the independent semantic work ledger/scheduler implementation, and static CI has PASSed. The remaining F2 task is runtime proof of that dual-state path against the current governed semantic checkpoint in SHADOW mode; it is not a request to add new analytical features or a realtime AI loop.

Canonical commit, scheduling, PR merge, formula changes, and live production deployment remain separate authority gates.

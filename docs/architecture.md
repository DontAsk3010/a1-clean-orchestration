# Architecture

## Authority separation

- **Google Drive** = canonical evidence plane and persistent project storage.
- **GitHub** = source control, review, CI, workflow definitions, and orchestration.
- **Owner Windows x64 environment** = compute/execution plane when authorized; persistent governed evidence remains in Drive.
- **Colab** = lab/bootstrap/manual fallback.
- **AI semantic reader** = research/test/behavior-atlas lane, not a live trading execution dependency.

GitHub is not a second analytical engine. Compute migration must not change frozen parser/routing/delta semantics or behavior-reading methodology.

## Permanent dual-state rule

DATA-PLANE state and SEMANTIC-RESEARCH work state are independent.

`VERIFIED_UNCHANGED` means source/data-plane bytes and governed derivatives do not require rebuild. It never means AI behavior research is complete. The permanent machine emits a separate semantic research ledger and authoritative semantic work queue so unfinished historical/replay research can resume from its exact checkpoint without rebuilding unchanged data-plane artifacts.

The semantic ledger/scheduler performs orchestration only. It creates no behavior labels, formula, score, threshold, selector, signal, or trading decision.

## Live trading execution rule — no AI in the latency-critical path

Future live trading is deterministic. AI must not sit between HPX/QHPX market data and the governed live trading result.

Target live topology is selected from deterministic implementations such as:

`HPX/QHPX -> AmiBroker governed engine -> Telegram transport`

or, when technically justified and proven equivalent:

`HPX/QHPX -> deterministic Python governed engine/bridge -> Telegram transport`

A hybrid is allowed and is likely preferable when AmiBroker remains the canonical analytical engine while Python handles non-analytical transport, persistence, logging, health, retry, and Telegram delivery:

`HPX/QHPX -> AmiBroker canonical deterministic state -> thin Python bridge/logging -> Telegram`

Python must not silently become a second analytical engine. If analytical execution is ever moved from AFL/AmiBroker to Python, the Python implementation requires explicit governed parity against the canonical formula/state semantics before it may become authoritative.

## Live-path selection criterion

Programming language does not determine trading accuracy. The authoritative route must be chosen from measured evidence. Compare candidate paths on the same recorded-live/replay source and require equivalence for:

- source field semantics and entitlement/availability states;
- event/tick/bar timestamp ordering and session boundaries;
- duplicate, missing, late, stale, and reconnect handling;
- canonical current-state outputs for every eligible ticker;
- deterministic formula outputs from identical inputs;
- end-to-end latency and jitter;
- restart/recovery behavior and state continuity;
- replay versus live/recorded-live parity;
- audit provenance from HPX/QHPX input to Telegram output.

Until such evidence says otherwise, prefer the shortest validated path with the fewest transformations between the HPX/QHPX feed and the canonical deterministic analytical engine. Because the current market-data/replay environment is already HPX/QHPX-linked to AmiBroker, AmiBroker should remain the first production analytical candidate; Python is initially a thin operational bridge unless a later parity gate proves a Python analytical path superior or necessary.

Telegram is presentation/transport only. It must not calculate independent thresholds, targets, rankings, or analytical conclusions.

## AI future role

AI may be used during research/testing to read behavior/event/journey evidence, reconcile pattern families, and help build the Behavior Atlas before narrative-to-deterministic translation is authorized.

Later, AI may also prepare **supplementary** external information such as issuer/company context, disclosures, market context, and news updates for Telegram. That lane is not implemented by the current task. Such information remains supplementary unless the governing Master explicitly authorizes it as an analytical input. It must preserve publication/known-at time so later information cannot be backdated into an earlier trading decision.

## Realtime research continuity

Even after live trading begins, historical/shadow-live/recorded-live research may continue asynchronously. Capture state, deterministic current market state, semantic research state, and post-session/EOD reconciliation remain separate. Semantic backlog never changes the live formula result and does not block authorized lossless market capture merely because AI research is behind.

## Persistent project data

Persistent project data remains in Google Drive. Canonical RAW and governed runtime targets are protected by the active commit policy. Shadow/parity output is written to a separate Drive staging area.

The owner laptop must not become canonical persistent storage for full RAW mirrors, baseline mirrors, or governed corpus artifacts. Bounded ephemeral scratch is permitted when technically required by the active source/job.

## Compute-only local working storage

The Windows executor may use bounded ephemeral local scratch only when technically necessary for streaming, SQLite, decompression, or source-scoped processing. Scratch is disposable and non-canonical. Governed artifacts, checkpoints, reconciliation evidence, and PASS/HOLD state must be persisted to the governed evidence plane.

## Current engineering state

Full dynamic corpus frozen-V2 shadow parity has PASSed. The permanent governed delta machine has also PASSed its observed no-change SHADOW path. The current branch is extending that same production machine with an independent semantic work ledger/scheduler; this is an operational continuity feature for research, not AI insertion into the future live trading loop.

Canonical commit, scheduling, PR merge, formula changes, and live production deployment remain separate authority gates.

# A1 CLEAN — MACHINE 1 DEDICATED RUNNER V1

STATUS: ACTIVE POOL EXPANSION — 3 OF 4 RUNNERS VERIFIED; RUNNER-05 ISOLATED SMOKE PENDING

## Purpose
Provide a reusable pool of dedicated Windows x64 self-hosted execution resources for Machine 1 AI semantic behavior-reading evidence extraction so Machine 1 does not queue behind Lane 2 compute. This is infrastructure isolation only. It does not create a new analytical engine and does not change behavior-reading methodology.

Machine 1 is the AI semantic/manual ticker-by-ticker, minute-by-minute market-behavior reading lane. Lane 2 is the separate algorithmic/numeric discovery/comparison lane. They remain analytically independent.

The Machine 1 runner pool is NOT tied to specific trading dates. A runner may execute any governed Machine 1 date assignment after the Dispatch Registry has assigned/pinned that worker/date. When a date reaches its required durable close/freeze/readback boundary, the physical runner becomes reusable for a later governed Machine 1 assignment.

## Authority and non-negotiable locks

The active Master, Current Execution, Behavior Handbook, Automation/Orchestration Handbook, Dispatch Registry, source manifests, and latest durable Machine 1 checkpoint remain authoritative.

Every runner in this pool MUST preserve all existing Machine 1 rules, including:

- exact canonical source identity / hash verification before evidence use;
- full actual source-supported rows only; no sampling, filtering, padding, interpolation, or synthetic bars;
- exact manifest order and exact source-row chronology;
- one explicitly claimed `SOURCE_ID + GENERATION + TRADING_DATE` per worker;
- hard date pin until `DATE_LOCAL_PASS`;
- no opening of the next date before current-date freeze/readback;
- no reread of durable completed ticker/context paths;
- same observation → event/journey semantic method and exact start/change/confirm/end timestamps;
- OPEN/right-censored state when the source does not support an end;
- date-scoped artifacts, atomic persistence, exact readback, Registry concurrency control, and exact next-resume recording;
- formula / score / threshold / selector / ranking / optimization / BUY-SELL / TP-SL / Telegram analytical logic remain closed;
- Machine 1 and Lane 2 remain analytically independent.

## Runner pool isolation contract

Shared dedicated Machine 1 runner labels:

`self-hosted, windows, x64, a1-clean-machine1`

No Machine 1 pool runner may carry:

`a1-clean-parity`

Reason: Lane 2 workflows use the parity route. Omitting that label prevents Lane 2 jobs from being scheduled onto the Machine 1 pool.

Target reusable pool size authorized by owner: 4 runners.

Pool identities:

- `A1-WINDOWS-MACHINE1-02` — VERIFIED / ACTIVE; existing runner directory `C:\actions-runner-machine1-02`.
- `A1-WINDOWS-MACHINE1-03` — VERIFIED / ACTIVE; runner directory `C:\actions-runner-machine1-03\actions-runner`; smoke run `35274664320` PASS.
- `A1-WINDOWS-MACHINE1-04` — VERIFIED / ACTIVE; runner directory `C:\actions-runner-machine1-04\actions-runner`; smoke run `35275632454` PASS.
- `A1-WINDOWS-MACHINE1-05` — REGISTERED / ONLINE / ISOLATED SMOKE PENDING.

These names identify physical runner instances only. They do NOT own a permanent trading date. Trading-date ownership exists only through the governed Dispatch Registry assignment/checkpoint state.

Each runner is compute-only. Canonical project evidence remains in governed Drive/GitHub authority locations. Local storage is non-canonical execution scratch/cache only, consistent with active automation authority.

## Activation gates per runner

Each physical runner becomes ACTIVE only after all gates below pass independently:

1. It is registered to `DontAsk3010/a1-clean-orchestration` under its own separate runner installation/work directory.
2. It has labels `self-hosted`, `windows`, `x64`, `a1-clean-machine1` and does **not** have `a1-clean-parity`.
3. It runs interactively under the established Windows user environment using `run.cmd`; it is not required to run as a Windows service.
4. Python 3.11 is available to that runner process.
5. The governed local RAW compute path is readable.
6. The known current authority source `Raw Des 02-31-2024.csv` matches canonical MD5 `b8d42b35c90d2dff8b18ae4e1734523b` and SHA256 `5bddb43f243e3cbb76504ecc38d8b0981e38866b7a4ea3b4557dcbbf3024712c` during the smoke probe.
7. The dedicated smoke workflow completes PASS with zero semantic/Registry/Drive mutation.
8. No in-flight Machine 1 job is retargeted mid-run. Routing changes occur only at a safe durable checkpoint boundary.
9. Before any worker/date is assigned, Dispatch Registry ownership is checked and claimed exactly as required by the Behavior Handbook.

## Routing policy

Governed Machine 1 evidence-extractor workflows use the generic pool selector:

```yaml
runs-on: [self-hosted, windows, x64, a1-clean-machine1]
```

The workflow must not select a runner by trading-date-specific label. GitHub may assign the job to any free ACTIVE runner in the Machine 1 pool. The Dispatch Registry and durable checkpoint—not the physical runner name—remain the authority for which worker owns which date and exact resume point.

Lane 2 remains on its existing runner selector and serialized controller. No Lane 2 workflow is changed by this Machine 1 pool expansion.

## Concurrency / date ownership

Additional compute capacity does not relax semantic governance. Parallelism is allowed only across distinct explicitly assigned dates/workers. The Dispatch Registry remains the source of truth for ownership. Two runners must never independently own/read the same open date.

Four ACTIVE Machine 1 runners may therefore process up to four distinct governed Machine 1 assignments concurrently when four distinct valid worker/date claims exist. They must not duplicate the same date, skip chronological governance, or auto-advance a worker beyond its pinned date merely because another runner becomes free.

A completed/frozen worker/date releases execution capacity for later governed assignments; the physical runner remains reusable and is never permanently associated with that completed date.

## Failure policy

If registration, source identity, hash, environment, or smoke verification fails for one pool member, that member is HOLD / NOT ACTIVE. Do not fall back by changing hashes, source scope, methodology, manifest order, or semantic rules. Other already-verified Machine 1 runners and Lane 2 remain unchanged.

## Activation state

Current pool target: `4` reusable Machine 1 runners.

Current verified state:

- `A1-WINDOWS-MACHINE1-02` — ACTIVE / smoke PASS / generic `a1-clean-machine1` route.
- `A1-WINDOWS-MACHINE1-03` — ACTIVE / smoke PASS / generic `a1-clean-machine1` route; smoke run `35274664320` verified Python 3.11.9, exact RAW MD5/SHA256, and all no-mutation gates.
- `A1-WINDOWS-MACHINE1-04` — ACTIVE / smoke PASS / generic `a1-clean-machine1` route; smoke run `35275632454` executed on runner_id `25` and completed successfully.
- `A1-WINDOWS-MACHINE1-05` — REGISTERED / ONLINE / ISOLATED SMOKE PENDING.

The pool is partially active. Only individually registered and smoke-PASS runners may accept governed Machine 1 work.

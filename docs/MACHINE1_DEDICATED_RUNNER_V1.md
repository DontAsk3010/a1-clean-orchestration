# A1 CLEAN — MACHINE 1 DEDICATED RUNNER V1

STATUS: STAGED / NOT ACTIVE

## Purpose
Provide a dedicated Windows x64 self-hosted execution resource for Machine 1 AI semantic behavior-reading evidence extraction so Machine 1 does not queue behind Lane 2 compute. This is infrastructure isolation only. It does not create a new analytical engine and does not change behavior-reading methodology.

## Authority and non-negotiable locks

The active Master, Current Execution, Behavior Handbook, Automation/Orchestration Handbook, Dispatch Registry, source manifests, and latest durable Machine 1 checkpoint remain authoritative.

This runner MUST preserve all existing Machine 1 rules, including:

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

## Runner isolation contract

Dedicated Machine 1 runner labels:

`self-hosted, windows, x64, a1-clean-machine1`

The dedicated Machine 1 runner MUST NOT carry label:

`a1-clean-parity`

Reason: current Lane 2 workflows select `a1-clean-parity`. Omitting that label prevents Lane 2 jobs from being scheduled onto the dedicated Machine 1 runner.

Recommended runner name:

`A1-WINDOWS-MACHINE1-02`

The runner is compute-only. Canonical project evidence remains in governed Drive/GitHub authority locations. Local storage is non-canonical execution scratch/cache only, consistent with active automation authority.

## Activation gates

The dedicated runner remains NOT ACTIVE until all gates below pass:

1. A second self-hosted runner is registered to `DontAsk3010/a1-clean-orchestration` under a separate runner installation/work directory.
2. The runner has labels `self-hosted`, `windows`, `x64`, `a1-clean-machine1` and does **not** have `a1-clean-parity`.
3. Python 3.11 is available.
4. The governed local RAW compute path is readable.
5. The known current authority source `Raw Des 02-31-2024.csv` matches canonical MD5 `b8d42b35c90d2dff8b18ae4e1734523b` and SHA256 `5bddb43f243e3cbb76504ecc38d8b0981e38866b7a4ea3b4557dcbbf3024712c` during the smoke probe.
6. The dedicated smoke workflow completes PASS with zero semantic/Registry/Drive mutation.
7. No in-flight Machine 1 job is retargeted mid-run. Routing changes occur only at a safe durable checkpoint boundary.
8. Before any worker/date is assigned to this runner, Dispatch Registry ownership is checked and claimed exactly as required by the Behavior Handbook.

## Routing policy after activation

Future Machine 1 evidence-extractor workflows may use:

```yaml
runs-on: [self-hosted, windows, x64, a1-clean-machine1]
```

Lane 2 remains on its existing runner selector and serialized controller. No Lane 2 workflow is changed by this infrastructure branch.

The currently queued/in-flight Machine 1 work must not be rewritten merely to activate this runner. Existing work may finish on its original runner. A future ticker/date worker transitions to the dedicated runner only after a durable checkpoint/readback boundary.

## Concurrency / date ownership

A new runner does not relax semantic governance. Parallelism is allowed only across distinct explicitly assigned dates/workers. The Dispatch Registry remains the source of truth for ownership. Two runners must never independently own/read the same open date.

If only one dedicated Machine 1 runner exists, jobs using `a1-clean-machine1` are naturally serialized on that runner. Additional future Machine 1 runners may share the generic label only if Dispatch Registry/date-worker governance remains enforced.

## Failure policy

If runner registration, source identity, hash, environment, or smoke verification fails, state is HOLD / NOT ACTIVE. Do not fall back by changing hashes, source scope, methodology, manifest order, or semantic rules. Existing governed Machine 1 and Lane 2 paths remain unchanged.

## Activation state

Current state: `STAGED_NOT_ACTIVE`.

Activation requires actual self-hosted runner registration plus smoke PASS. Until then, existing Machine 1 routing remains authoritative.

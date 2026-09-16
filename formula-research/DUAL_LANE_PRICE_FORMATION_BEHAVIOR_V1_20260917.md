# A1 CLEAN / QHPX — DUAL-LANE PRICE × FORMATION BEHAVIOR RESEARCH V1

Status: RESEARCH_ONLY_NOT_CANONICAL
Date: 2026-09-17 WIB
Authority: ACTIVE MASTER + CURRENT EXECUTION + FORMULA RESEARCH HANDBOOK V2 + owner-locked multi-layer behavior rule
Reserved OOS: `Raw Maret 03-31-2025.csv` — MUST REMAIN UNTOUCHED

## 0. Core correction

The next research pass MUST NOT read only price-path behavior and MUST NOT read only price-formation evidence.

The atomic research object is the synchronized pair:

`PRICE_BEHAVIOR_LANE(t) × FORMATION_BEHAVIOR_LANE(t)`

plus their causal relationship at the same known-at time:

`ALIGNMENT / LEAD-LAG / DIVERGENCE / CONTRADICTION / FAILURE`.

Price is not reduced to a passive outcome label. Price has its own behavior trajectory: compression, displacement, hold, giveback, pullback, retest, reclaim, high/low progression, acceptance/rejection, second wave, failure and recovery. Formation evidence has its own trajectory: value/volume effort, acceleration, valid flow/NBSS state, persistence/collapse and effort-without-response. Research must preserve both trajectories before translating them into a candidate action state.

## 1. Current source capability boundary

This V1 pass uses only evidence already present in the durable normalized cache and already-proven current formula-research semantics. It may use:

- OHLC price path and running high/low/open relationships;
- volume;
- validated trade value;
- validated NBSS/flow fields where `flow_available` and `mechanism_eligible` permit them;
- derived same-clock relative states already used by V11/V12;
- prior-day behavior context already produced by governed history functions.

This V1 MUST NOT invent broker-level flow, tick/Time & Trade, L1/L2/order book, queue or financial/issuer fields if they are not physically present in the current durable cache. Those lanes remain eligible for later enrichment when source capability and semantics are proven.

Missing flow remains UNKNOWN/UNAVAILABLE, never zero.

## 2. PRICE_BEHAVIOR_LANE

At each publication snapshot preserve, where causally available:

- current path and path change versus prior publication;
- same-clock relative price progress;
- close-location acceptance/rejection;
- range expansion/contraction relation;
- running-high progression / fresh-high state;
- running-low behavior and OPEN defense/break for OPEN LOW lineage;
- giveback/pullback/retest;
- reclaim/reacceleration;
- hold versus surrender of prior progress;
- low stabilization / renewed lower-low when directly observable.

A price state is a sequence, not a final-day label.

## 3. FORMATION_BEHAVIOR_LANE

At the same publication snapshot preserve, where available/proven:

- value wake relative to prior same-clock history;
- volume wake relative to prior same-clock history;
- valid flow/NBSS wake relative to prior same-clock history;
- value/volume acceleration;
- flow sign and flow persistence when valid;
- formation persistence across later snapshots;
- formation collapse after a prior wake;
- effort present while price does not progress;
- seller pressure with limited downside response;
- transition from sell pressure to buy/flow support where causally observed.

No formation state is allowed to overwrite price behavior. Both must remain separately inspectable.

## 4. RELATIONSHIP LANE

Each synchronized snapshot is classified descriptively, without a score:

- `ALIGNED_EXPANSION`: price is constructive and formation evidence is active;
- `FORMATION_LEADS`: formation evidence is active while constructive price response has not yet appeared;
- `PRICE_LEADS`: constructive price progress appears while current formation evidence is not active;
- `BOTH_QUIET_OR_UNCONFIRMED`: neither side supplies enough evidence;
- `SELL_PRESSURE_RESILIENCE`: valid sell-side flow exists but downside price response weakens/does not progress;
- `FORMATION_COLLAPSE`: prior formation activity disappears;
- `PRICE_GIVEBACK`: price retreats after prior progress;
- `OPEN_DEFENDED` / `OPEN_BROKEN` only for causally observed OPEN LOW journey.

The relationship may change at every publication. The change itself is research evidence.

## 5. First candidate state-machines

These are structural research candidates, not canonical signals and not final parameter choices.

### DL01 — FLOW_LEADS_PRICE_RELEASE_HOLD

`valid flow wake while price not constructive`
→ `flow persists while price still contained`
→ `price response appears and aligns with formation`
→ `aligned progress holds`.

Purpose: test whether persistent causal flow lead is different from same-snapshot flow+price coincidence.

### DL02 — PRICE_LEADS_FORMATION_CONFIRM_RETEST_REACCEL

`price makes accepted progress before formation confirmation`
→ `formation catches up / confirms`
→ `controlled price retest while formation remains present`
→ `price reaccelerates beyond first confirmed progress`.

Purpose: preserve price-leading cases rather than assuming formation must always lead.

### DL03 — EFFORT_NO_RESPONSE_THEN_EFFICIENCY_FLIP

`value/volume effort wakes while price response is weak`
→ `effort persists without progress`
→ `price response flips constructive while effort remains`
→ `constructive response holds`.

Purpose: explicitly read the change in effort-response efficiency.

### DL04 — SELL_PRESSURE_RESILIENCE_CONTROL_TRANSFER

`valid sell pressure exists`
→ `price stops producing proportional downside / low stabilizes`
→ `flow/formation turns while price becomes constructive`
→ `new control state holds`.

Purpose: distinguish true control transfer from a temporary pause in decline.

### DL05 — TWO_WAVE_PRICE_FORMATION_RELOAD

`first aligned price+formation impulse`
→ `price gives back/pulls back while formation remains present`
→ `second aligned impulse exceeds first response`
→ `second impulse holds`.

Purpose: reject one-wave spikes while retaining price behavior and formation persistence separately.

### DL06 — OPEN_LOW_DEFEND_RECLAIM_FORMATION

`OPEN remains running low + initial aligned push`
→ `price pulls back but OPEN remains defended and formation remains present`
→ `price reclaims/exceeds first push with aligned formation`
→ `fresh high / renewed progress holds while OPEN remains defended`.

Purpose: replace shallow `Open=Low + CHG + effort` logic with a causal synchronized journey.

### DL07 — FORMATION_PAUSE_PRICE_HOLD_REWAKE

`aligned expansion`
→ `formation temporarily weakens while price retains prior progress`
→ `formation re-wakes before/with renewed price progress`
→ `renewed aligned progress holds`.

Purpose: test whether temporary effort pauses during constructive price holding are materially different from true formation collapse followed by failure.

## 6. Near-twin contract

For every candidate, preserve non-completing journeys that reached a comparable intermediate state. A near-twin is not an arbitrary loser. It must share the early synchronized state and then diverge.

Required divergence checks include:

- formation persists vs collapses;
- price holds vs gives back;
- flow leads then price responds vs flow leads but price never responds;
- price leads then formation confirms vs price leads without confirmation;
- OPEN defended vs OPEN broken;
- first wave reloads vs first wave dies;
- sell pressure loses effectiveness vs downside resumes.

If the evidence is still indistinguishable, state remains AMBIGUOUS/UNCONFIRMED rather than forcing a prediction.

## 7. Evaluation contract

- Use durable cache only; no silent RAW reread.
- Use governed Discovery / Validation A / Validation B blocks unchanged.
- Preserve all negative and non-completing cases.
- First signal time = first publication where the complete causal state-machine is satisfied.
- Future bars are outcome evaluation only.
- Store signal support, unique ticker-days, net MFE distribution, MAE, EOD result and near-twin metrics.
- Preserve first transition time and final completion time for examples.
- Strict robustness gate remains governed by current Formula Research authority unless explicitly changed.
- Reserved March-2025 OOS remains untouched.

## 8. Research interpretation rule

This pass is explicitly designed to answer:

`What is PRICE doing?`

AND simultaneously:

`What is the proven FORMATION evidence doing?`

THEN:

`Which side leads? Do they align? Do they diverge? What changes first? Does the price path hold, reclaim, reaccelerate, fail or recover after that change?`

Only after this synchronized journey is observed may a candidate action state be evaluated.

END

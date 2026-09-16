# Claude MG Research Ledger

Status: INITIALIZED
Branch: `research/claude-mg-discovery`

Use this file as an append-only chronological ledger for independent Claude MG research.

For every experiment record:
- timestamp / commit SHA;
- governed source(s) used;
- hypothesis and causal rationale;
- exact precursor features;
- exact ignition features;
- anti-failure features;
- discovery block;
- validation block(s);
- event/support counts;
- unique ticker-days / dates;
- outcome metrics including Q10/Q25/median/Q75/Q90 net MFE, MAE, time-to-positive, TP1/TP2 where available;
- winner coverage / missed winners / false positives;
- result: PASS / FAIL / INCONCLUSIVE;
- reason for rejection if failed;
- paths to result JSON, code, workflow, and artifact/run ID.

Do not delete failed experiments. They are evidence.

---

## Entry 001 — 2026-09-15 — PHASE 0 AUDIT (not a formula experiment)

- **Timestamp / commit**: 2026-09-15, committed locally on `research/claude-mg-discovery`
  (not yet pushed — session lacked GitHub push authorization at time of this entry; see
  `RESEARCH_AUDIT.md` "Session blockers").
- **Governed source(s) used**: none executed against raw bars yet. Reviewed (read-only):
  all 8 Drive master-authority docs + historical `004_MASTER_HANDBOOK`; full git history
  of `formula/current-clean-research-v1` (V2 through V8d, all `*-requests/current.json`,
  all `plans/formula/*.json` and `plans/lane2/*.json`, both frozen formula packs and the
  one evidence file); `docs/architecture.md`/`parity-contract.md`/`recovery-contract.md`;
  Google Drive governed data-plane folder structure (manifests/indexes only, no bulk
  data pulled).
- **Hypothesis and causal rationale**: N/A — this entry is the mandatory pre-formula
  audit CLAUDE.md requires before any candidate may be proposed, not an experiment.
- **Exact precursor/ignition/anti-failure features**: N/A this entry.
- **Discovery block / validation block(s)**: N/A this entry; confirmed for future
  entries: discovery = `Raw Des 02-31-2024.csv`, validation =
  `Raw Jan 01-31-2025.csv` + `Raw Feb 03-28-2025.csv`, untouched OOS =
  `Raw Maret 03-31-2025.csv`.
- **Event/support counts, outcome metrics**: N/A this entry.
- **Result**: **INCONCLUSIVE / NOT-APPLICABLE (audit phase, no formula tested)**.
  Produced `RESEARCH_AUDIT.md` (populated) and `HYPOTHESIS_REGISTRY.json` (11 proposed
  hypotheses, none tested).
- **Reason / next step**: GitHub Actions REST API was unavailable from this session
  (sandbox-level block, confirmed against a control repo — not a repo-specific
  permission issue) so the specific run IDs CLAUDE.md names (`35006408023`,
  `34999944377`, `35013142224`, `35030436199`) could not be inspected directly; their
  content is reconstructed instead from `plans/formula/*.json`, frozen-pack evidence
  files, and commit history, and is recorded as such in `RESEARCH_AUDIT.md`. Next
  planned experiment: **H05** (near-twin failure discriminator for the frozen
  `MG_RR_FLOW_RENEW_V4` candidate's Jan/Feb losing tail) once execution access to the
  governed data plane is set up — this is the most concretely evidence-backed open
  problem found (see `RESEARCH_AUDIT.md` section 5).
- **Paths**: `research/claude-mg-discovery/RESEARCH_AUDIT.md`,
  `research/claude-mg-discovery/HYPOTHESIS_REGISTRY.json`. No code, workflow, or
  artifact/run ID produced by Claude's lane yet.

---

## Entry 002 — 2026-09-16 — "Absorption-Then-Wake" formula coded, not yet executed

- **Timestamp / commit**: 2026-09-16, committed locally on
  `research/claude-mg-discovery` (push still pending GitHub authorization).
- **Governed source(s) used**: none executed yet against real bars. This entry
  documents code + a synthetic-fixture self-test, not an empirical result.
- **Hypothesis and causal rationale**: operationalizes H03/H04/H05 together —
  a ticker in a decline-or-dormant phase (relative to its own history) whose
  trade-value/NBSS flow does NOT fade in proportion to price (absorption),
  sustained for a learned minimum number of consecutive days
  (`min_absorption_streak_days`), followed by a same-day ignition (positive
  path, upper-range close, value acceleration). See the module docstring in
  `src/a1clean/formula_research/claude_absorption_wake_v1.py` for the full
  Q1–Q6 self-posed question list this code answers.
- **Exact precursor/ignition/anti-failure features**: `_trailing_return_pct`
  (dormancy), `_flow_persistence_ratio` (absorption), `absorption_streak_days`
  (duration), `_ignition_today` (wake). All three cut-points
  (`dormant_return_cutoff_pct`, `flow_persistence_cutoff_ratio`,
  `min_absorption_streak_days`) are learned only from the discovery source at
  runtime (median-based, corpus-relative — no hand-picked constants) and
  frozen into a thresholds file for the validate phase. Strictly causal:
  every feature at day *i* reads only days `< i`; forward bars are used only
  inside `_forward_outcome`, which never feeds back into a feature (unit-
  tested explicitly).
- **Discovery block / validation block(s)**: wired to run discovery on
  `Raw Des 02-31-2024.csv` (`claude-mg-absorption-wake-v1-requests/current.json`)
  and, once discovery numbers exist, a follow-up validate-phase request against
  `Raw Jan 01-31-2025.csv` + `Raw Feb 03-28-2025.csv`. March 2025 is refused
  fail-closed by `_reject_oos_source` regardless of what any request file says
  (unit-tested).
- **Event/support counts, outcome metrics**: **not yet available** — this
  module has only been exercised against hand-built synthetic fixtures
  (6 unit tests, all passing, plus the full existing repo suite: 189/189
  passing, `compileall` clean) to prove the mechanism fires correctly on a
  constructed absorption-then-wake case and correctly stays silent on a
  constructed "decline with fading flow" case. No real governed data has been
  read by this module yet.
- **Result**: **CODE_READY — awaiting execution**. Cannot be run from this
  Cowork session: the actual data read happens via
  `GovernedSourceReader`/`build_drive_api` using service-account credentials
  bound only on the project's own self-hosted Windows GitHub Actions runner
  (`A1_DRIVE_READER_CREDENTIALS`) — this session has neither that credential
  nor (still) push authorization to `DontAsk3010/a1-clean-orchestration` to
  land this commit and let the runner pick it up. Pulling the raw governed
  data directly into this session instead (bypassing the runner) is not
  practical either: the governed RAW months are ~400–800MB each and the only
  Drive access this session has returns file content inline, which would cost
  on the order of millions of tokens for a single file — far beyond a
  workable budget, and this was deliberately not attempted.
- **Reason / next step**: land this commit once push access exists; the
  existing workflow (`.github/workflows/claude-mg-absorption-wake-v1.yml`)
  then runs automatically on push to this branch and uploads a real
  discovery-phase result artifact. After that, re-derive V4's exact
  K06/HELD_FLOW/PRIOR3_RECLAIM/REGAIN signature specifically (H05's precise
  scope) and add the STUMPY motif crosscheck (H03) against whatever events
  this module actually flags.
- **Paths**: `src/a1clean/formula_research/claude_absorption_wake_v1.py`,
  `tests/test_claude_absorption_wake_v1.py`,
  `claude-mg-absorption-wake-v1-requests/current.json`,
  `.github/workflows/claude-mg-absorption-wake-v1.yml`.

---

## Entry 003 — 2026-09-16 — Entry 002's module EXECUTED on the self-hosted runner (first real governed-data run)

Supersedes Entry 002's `CODE_READY — awaiting execution` status. Entry 002 is
left unedited above, as required.

- **Governing authority actually read for this entry** (Master §25: the loaded
  revision must be recorded in run provenance):
  - **MASTER HANDBOOK** `1FVWKgoeWU9MsnOd3i8HOpprg36XrxgKInf6BQU6QTKQ`
    (`VERSION: 20260913 CLEAN REWRITE V1 — NO-FIXED-CUTOFF / DUAL-READER
    FULL-SOURCE PARITY`) — read in full, line 1 through `END`.
  - **CURRENT EXECUTION** `1AdtN9N7oIYwsHr_7-R6UzBREx9DJd4s291iZJou6GZU` — top
    override block read in full; remainder covered by targeted search only
    (formula-gate, OOS, Claude/MG, resume points). **Not read line-by-line in
    full — stated plainly rather than implied.** Sub-Master, Behavior Handbook,
    Stable Handoff, Telegram sub-sub master and decision book: **NOT read in
    this session.** The Master §9A transition handshake is therefore only
    partially satisfied.
  - **Formula gate at time of this run**: Master §20 holds formula/model/
    threshold/score/selector work CLOSED until explicit owner authorization,
    and §20A repeats that its roadmap "bukan izin untuk mulai membuat formula
    sekarang". That closure is **explicitly lifted for candidate work** by
    CURRENT EXECUTION's top override `CURRENT TOP OVERRIDE — OWNER AUTHORIZED
    CANDIDATE FORMULA + AFL RESEARCH IN PARALLEL — 20260915`:
    *"CANDIDATE FORMULA/AFL RESEARCH = OPEN/AUTHORIZED. FINAL/CANONICAL FORMULA
    PROMOTION = STILL CLOSED."* Current Execution is the Level-2 current-status
    authority and is newer, so this run sits inside authorized scope and is
    **not** an authority breach. Canonical/live/Telegram promotion stays closed,
    which matches this repo's `RESEARCH_ONLY` rule.
- **Governance gaps this run exposes** (recorded, not resolved, and not
  silently worked around):
  1. The authorized scope names `formula/current-clean-research-v1` as the
     GitHub research branch and candidate spec
     `A1_HANDBOOK_DERIVED_CANDIDATE_FORMULAS_V1` with families F01–F06. A
     search of Current Execution returns **no occurrence of "claude", "MG",
     "MULAI GENIT" or "EARLY_POTENTIAL"** — this Claude lane and this
     candidate exist only in the repo's `CLAUDE.md`, not yet in Drive
     governance. Under Master §15's cumulative-update contract the lane needs a
     registered canonical home; until then its standing is OWNER-DIRECTED-IN-REPO
     but UNREGISTERED-IN-DRIVE.
  2. Master §20A step 3 requires a **BEHAVIOR-TO-FORMULA SPECIFICATION**
     (observable evidence, source fields, prior condition, sequence, timing,
     causal known-at, contradiction/failure/lookalike, invalidation, outcome
     relationship, availability handling, provenance) **before formula coding**.
     Absorption-Then-Wake v1 went from hypothesis registry straight to code
     without that specification artifact. Its cut-points are at least learned
     from discovery data and frozen rather than invented, which respects the
     §20A prohibition on imposed generic thresholds — but the specification
     step is still owed.
  3. **SOURCE SEMANTIC LOCK** (Current Execution): `RAW_Aux2=TRADE_VALUE_1M`
     and `RAW_OpenInterest=NBSS_VALUE_1M` hold **only where availability/
     mechanism eligibility is proven**, and a zero in an unproven source/
     mechanism context is not automatically neutral. This formula's flow-
     persistence leg leans on NBSS; that eligibility proof must be confirmed
     per ticker-day rather than assumed before any metric from this run is
     treated as meaningful.
  4. `AUG19_20250819` is **excluded by governance** from formula/model fitting,
     threshold derivation, candidate selection, validation and OOS evidence.
     December 2024 discovery is unaffected, but any later validation scope must
     honour this exclusion.
- **Timestamp / commit SHA**: 2026-09-16. Commits `15871e0` and `bf46bef` were
  transferred from the earlier push-blocked session via a verified `git bundle`
  (sha256 `d6f262ab84fb467255076138e653d7fe7778d89d725a66898ed59f5cf503455d`,
  `git bundle verify` = okay) and landed on `research/claude-mg-discovery` as a
  clean fast-forward `f96fc7e..bf46bef` — no amend, rebase, squash, cherry-pick,
  reimplementation, or force. Remote tip confirmed
  `bf46bef688c601e13b4d81acd5a4061a2f8e901c` by `git ls-remote`.
- **Workflow / run ID**: `.github/workflows/claude-mg-absorption-wake-v1.yml`,
  run **`35070450297`** (run_number 1, attempt 1, event `push`), job
  `104710489040`. Runner: self-hosted `A1-WINDOWS-COMPUTE`, labels
  `[self-hosted, windows, x64, a1-clean-parity]`. Queued 07:48:53Z, started
  09:15:23Z (runner offline until then), completed 09:19:58Z. Conclusion:
  `success`.
- **Source identity**: `Raw Des 02-31-2024.csv` (December 2024), read on the
  runner through `GovernedSourceReader`/`build_drive_api` under the
  runner-bound `A1_DRIVE_READER_CREDENTIALS` service-account credential. The
  workflow's `Verify Drive bindings` step passed, so the credential resolved.
- **Formula / signature**: Absorption-Then-Wake v1 (hypotheses H03/H04/H05) —
  decline-or-dormant precursor phase whose trade-value/NBSS flow does not fade
  with price, persistence tracked as a consecutive-day streak, plus a same-day
  ignition requirement.
- **Phase / discovery period**: `discover` on December 2024 only.
  `precursor_window_days=8`, `horizons_days=1,3,5,8`,
  `min_streak_grid=2,3,4,5,6,8`.
- **Validation period**: none in this run. Jan/Feb 2025 validation is still
  pending a follow-up `validate`-phase request carrying the frozen thresholds
  this run produced.
- **March 2025 OOS**: untouched. `_reject_oos_source` plus the workflow's
  `Validate request` guard both remained in force; the request names December
  2024 only.
- **Future data label-only**: yes — unchanged from Entry 002 and still
  unit-tested. Forward bars are read only inside `_forward_outcome` and never
  feed back into a feature.
- **Execution evidence actually inspected** (not assumed from the green tick):
  full job log read directly. Checkout resolved to `bf46bef688c601e13b4d81acd5a4061a2f8e901c`;
  `compileall` clean; full suite `189 passed in 1.15s`; the research module ran
  09:15:56Z → 09:19:46Z (≈3m50s of real work, consistent with a genuine
  full-month governed read rather than an immediate no-op exit) and printed
  `{"pass": true, "phase": "discover", "output": "claude-mg-absorption-wake-result.json"}`.
  Artifact `claude-mg-absorption-wake-v1-35070450297` (ID `10439505834`,
  1484 bytes, zip sha256
  `06ae15fe31f6853dc08a57d82de48d32d4b50183ee897ea6821ae861472a735c`) uploaded
  successfully.
- **Event/support counts, unique ticker-days/dates, learned+frozen thresholds,
  Q10/Q25/median/Q75/Q90 net MFE, MAE/pre-peak MAE, time-to-positive,
  time-to-peak, reward/adverse, TP1/TP2, EOD retention, coverage/recall,
  missed winners, false positives, unconditional baseline**: **UNAVAILABLE
  from this session — not zero, not inferred.** All of these live inside the
  result JSON in the artifact, and this session cannot read it: the artifact
  blob host `productionresultssa6.blob.core.windows.net` is refused by this
  environment's egress proxy (`connect_rejected`, gateway 403 — organization
  network policy) on both `curl` and `WebFetch`. The 1484-byte artifact size
  confirms a small summary JSON was written but says nothing about its
  contents, so **no claim is made here about whether the formula performed
  well, poorly, or fired at all.**
- **Result**: **EXECUTED — METRICS UNREAD.** The pipeline is proven end-to-end
  (push → self-hosted runner → governed Drive read → result artifact); the
  research question itself remains unanswered pending the numbers.
- **Reason / next step**: retrieve the artifact from a context with egress to
  GitHub artifact storage (the run's own Downloads panel on
  `https://github.com/DontAsk3010/a1-clean-orchestration/actions/runs/35070450297`,
  or the runner-local
  `C:\Users\feri-admin\actions-runner-a1\_work\a1-clean-orchestration\a1-clean-orchestration\claude-mg-absorption-wake-result.json`),
  commit it under `research/claude-mg-discovery/results/` (directory does not
  exist yet), then record the real metrics in a new ledger entry and judge the
  candidate against the breadth/validation bar in `CLAUDE.md` — explicitly
  including whether it clears the "~55–59% positive rate with negative Q25 is
  not a good answer" threshold. A future workflow revision that writes the
  result JSON into the repo alongside the artifact would remove this retrieval
  gap entirely. Only after real numbers exist should the frozen thresholds be
  replayed unchanged on Jan/Feb 2025.
- **Paths**: run
  `https://github.com/DontAsk3010/a1-clean-orchestration/actions/runs/35070450297`;
  artifact `claude-mg-absorption-wake-v1-35070450297` (ID `10439505834`);
  code/workflow/request paths unchanged from Entry 002.

---

## Entry 004 — 2026-09-16 — Drive authority + GPT-lane December evidence read; two Entry 003 gaps closed, one architectural mismatch found

Owner granted Drive search access to locate material relevant to this lane.
Read, in full to `END`: **`00_A1_CLEAN_FORMULA_RESEARCH_HANDBOOK_ACTIVE`**
(Drive ID `1sQu0l2qwvsjItmBycRh3siMajKEQknHOMBLlBQd3I-Q`, `VERSION: 20260915 V1`)
— the Branch 07 handbook required by Master §9A step 4, which Entry 003
recorded as unread. Also read in full the GPT lane's governed December replay
result `CANDIDATE_FORMULA_REPLAY__FORMULA_REPLAY_FULL_DES2024_20260915_01.json`
(Drive ID `12uivFUAhM-H01ANXQbjdPmi8qCMOyMQ-`, schema
`A1_CANDIDATE_FORMULA_CAUSAL_REPLAY_RESULT_V1`, status
`RESEARCH_RESULT_NOT_CANONICAL`).

### Entry 003 gap 1 (lane unregistered) — REFRAMED, not a defect of this lane

The Branch 07 handbook §3 names the **CURRENT PRIMARY FAMILY = EARLY_POTENTIAL /
👀 MULAI GENIT**, with output contract `CODE | PRICE | CHG% | TP-1 | TP-2`,
first snapshot 09:00 WIB then **every 5 minutes**, TP-1/TP-2 dynamic per
snapshot and never Telegram-side. So MG is the governed primary target, and
this lane is aimed at the right family. What remains true is that
`research/claude-mg-discovery` is still not named in Drive governance (§8 names
only `formula/current-clean-research-v1`); the lane's *subject* is governed,
its *branch* is not yet registered.

### Entry 003 gap 2 (missing behavior-to-formula specification) — CLOSED, was overstated

Entry 003 implied a completed behavior atlas was owed first. That was wrong in
context. Current Execution shows Machine 1 semantic reading is only at 123/892
ticker paths for 2024-12-02 alone, and the 20260915 override authorizes formula
research explicitly **without waiting for Machine 1**. Branch 07 handbook §11
states candidates are "derived from handbook behavior requirements and current
internal candidate-state evidence" — i.e. the specification source is handbook
§4 **REQUIRED MG RESEARCH DOMAINS** plus F01–F06 replay evidence, not a
finished atlas. Handbook §4 domains: prior state; initiation quality;
multi-bar/path persistence; price/high-low lifecycle; participation/activity;
effort-versus-response; volatility/range development; progress retention;
extension/remaining room; tradability/liquidity; valid flow; market/sector
context where source-supported; proven microstructure only when physically
available. Required failure/lookalike controls: one-bar spike without
continuation; mature/high-CHG chase; large effort with poor response;
rejection/giveback; thin-liquidity jump; unstable path; stale/partial/invalid
data.

### Entry 003 gap 3 (NBSS eligibility) — CLOSED, exact governed policy located

The December replay binds it explicitly:
`flow_availability_policy = SOURCE_SCOPED_HISTORICAL_SEMANTICS_PLUS_ROW_NBSS_NONZERO_POPULATION_PROOF;`
`PHYSICAL_ZERO_REMAINS_UNKNOWN_UNTIL_INDEPENDENT_AVAILABILITY_IS_BOUND`, with
field mapping `nbss = RAW_OPENINT_PHYSICAL`, `trade_value = RAW_AUX2_PHYSICAL`.
A physical NBSS zero is **UNKNOWN**, not a real zero. Claude's
`claude_absorption_wake_v1` leans on NBSS flow persistence and must be audited
against this rule before any metric it produces is treated as meaningful; if it
reads physical zeros as genuine low flow, its absorption leg is measuring an
availability artifact, not behavior.

### NEW FINDING — architectural mismatch between this lane's candidate and the MG contract

The governed MG family is **intraday**: published every 5 minutes from 09:00
WIB, with per-snapshot dynamic TP-1/TP-2. The GPT lane's replay matches that
shape — `forward_horizons_regular_bars: [5, 15, 30, 60]`, evaluated on
1,350,134 eligible regular-session rows. Claude's Absorption-Then-Wake v1 is a
**daily** construct (`precursor_window_days=8`, `horizons_days=1,3,5,8`) and
emits no TP-1/TP-2 at all. A multi-day precursor is legitimate and expected
(handbook §4 "prior state"), and F06 already occupies that role, but a
candidate whose ignition and outcome are measured in days cannot satisfy a
5-minute snapshot publication contract as written. **This is the most material
problem found so far, and it is structural, not a threshold-tuning issue.**

### GPT-lane December baseline now available to this lane as control evidence

Same source as Claude's own run (`Raw Des 02-31-2024.csv`, Drive ID
`1wvBmhpQIV-evJJOPN_g8nks3KZBzmVHC`, sha256 `5bddb43f...4712c`), generation
`BEHAVIOR_UNIFORM_COLAB_SEMANTIC_GEN_20260910_01`, 16,929 ticker-day packets,
1,621,335 raw rows, `winner_only_filter_used: false`,
`future_data_used_for_candidate_state: false`. Positive-forward-rate and mean
forward return by component (5 / 15 / 30 / 60 regular bars):

| component | pos rate 5→60 | mean fwd return |
|---|---|---|
| F01A BUY_STALL_BASIC | 21.4% → 30.9% | negative at every horizon |
| F01B BUY_STALL_STALE_HIGH_EFFORT | 22.7% → 31.7% | negative at every horizon |
| F02A SELL_RESILIENCE_BASIC | 32.0% → 35.6% | **positive at 5/15/30**, negative at 60 |
| F03A NEW_HIGH_EVENT | 21.7% → 30.8% | negative (≈ −0.0025 to −0.0028) |
| F04A EARLY_STRENGTH_RETAINED | 12.6% → 25.1% | negative (≈ −0.0033 to −0.0036) |
| F04B LATE_LIFT | 10.6% → 23.0% | negative |
| F05A SESSION_OPEN_RECOVERY | 16.9% → 26.3% | **worst** (≈ −0.0046 to −0.0053) |

Reading: every standalone component except F02A SELL_RESILIENCE has negative
mean forward return on the full universe — empirical support for handbook §9's
refusal to accept standalone BUY_STALL / NEW_HIGH / EARLY_STRENGTH / RECOVERY
as MG. F05A SESSION_OPEN_RECOVERY being the worst is a direct warning for any
"decline → stabilise → ignition" shape, which is close to Claude's H04 recovery
framing. F02A's mild positive edge is the only standalone signal pointing the
right way and deserves attention as a *component*, not as MG.

Availability gaps in that same evidence, recorded as UNKNOWN and not zero:
`F02B_SELL_RESILIENCE_ACCEPTANCE_RENEWAL` and `F05B_CANONICAL_VWAP_RECOVERY`
are **100% UNKNOWN** across all 1,350,134 rows (VWAP is not synthesized);
`F04B_LATE_LIFT` is 84% UNKNOWN; `F04A` 25% UNKNOWN; `F05A` 10% UNKNOWN. Any
Claude-side union/intersection against these components must carry the UNKNOWN
mass explicitly rather than treating it as FALSE.

- **Result**: **AUTHORITY AND BASELINE ESTABLISHED — CANDIDATE SHAPE IN
  QUESTION.** No Claude formula metric is claimed here; Entry 003's run metrics
  remain UNAVAILABLE.
- **Next step**: decide the candidate's time base before spending another
  governed run. Either re-express absorption-then-wake as a multi-day precursor
  feeding a **5-minute intraday ignition + dynamic TP-1/TP-2**, matching the MG
  contract, or keep the daily version explicitly as a non-MG swing-context
  study and say so. Then audit the NBSS physical-zero handling, and compare
  Claude candidates against the F01–F06 table above as failure controls and
  near-twin evidence rather than re-deriving them.
- **Paths**: Branch 07 handbook `1sQu0l2qwvsjItmBycRh3siMajKEQknHOMBLlBQd3I-Q`;
  December replay `12uivFUAhM-H01ANXQbjdPmi8qCMOyMQ-`; Branch 07 workspace
  `1ePhRnCs0ZnsgI-_kf19lhFpOr4C93D4H`; audit/readback
  `1uQKSZD8KbOZ2j3moyZiH1EuJPlEhEAuC`.

---

## Entry 005 — 2026-09-16 — V2 built to the governed MG contract: multi-day precursor → intraday snapshot + dynamic TP

Direct response to Entry 004's architectural mismatch. Owner instruction was to
adjust the candidate to the contract rather than relabel it, noting that fitting
the contract is precisely where the difficulty lies.

- **What changed**: new `src/a1clean/formula_research/claude_mg_intraday_v2.py`.
  v1 is left untouched as evidence, not deleted. v1 collapsed each day into one
  daily aggregate and measured outcomes in days; v2 keeps the multi-day
  absorption precursor as *context* and moves ignition, publication and outcome
  onto the intraday snapshot grid required by Branch 07 handbook §3.
- **Contract alignment**: emits `PRICE | CHG% | TP-1 | TP-2` per qualifying
  snapshot, with actual source timestamp retained. Forward horizons are regular
  bars `5,15,30,60` — deliberately the same axis as the GPT lane's governed
  December replay, so the two lanes compare head-to-head on identical
  measurement rather than on rescaled numbers.
- **Causality**: at day D bar t, state reads only complete days < D plus bars
  0..t of D. Forward bars live solely inside `_forward_from_bar`, clipped to the
  same trading date so no outcome can borrow the next day's open. This is
  enforced by test, not by assertion: `test_forward_bars_cannot_change_the_signal`
  runs identical history against two opposite futures and requires the fired
  bar index and every published field to match while the outcomes diverge.
- **Targets are derived, not chosen**: TP-1/TP-2 are
  `price + multiple × volatility_unit`, where `volatility_unit` is the median
  prior-window daily range and the multiples are the median and Q75 of the
  realized favorable-excursion distribution measured on discovery in volatility
  units. No fixed percentage appears anywhere, satisfying Master §20A.6.
  `test_targets_scale_with_measured_volatility_not_a_fixed_percentage` pins this:
  identical price and identical gates, calm vs volatile prior context, different
  targets.
- **Failure/lookalike controls** (handbook §4, all implemented and counted, so
  suppressed candidates stay visible as evidence instead of disappearing):
  `stale_or_partial_data`, `no_precursor_context`, `absorption_streak_too_short`,
  `thin_liquidity`, `mature_chase`, `one_bar_spike_no_continuation`,
  `effort_without_response`, `rejection_giveback`, `unstable_path`,
  `no_remaining_room`.
- **Entry 004 gap 3 honoured**: flow comes from `packet_to_formula_bars`, where a
  physical NBSS zero yields `flow_available=False`.
  `test_physical_nbss_zero_is_unknown_not_neutral` proves a zero-NBSS day is
  refused as `stale_or_partial_data` rather than read as low flow.
- **Snapshot accounting**: MG republishes while criteria hold, but only the
  first qualifying snapshot per ticker-day is recorded for outcome accounting,
  so one persistent opportunity cannot inflate into dozens of independent wins.
- **Workflow change worth keeping**: `.github/workflows/claude-mg-intraday-v2.yml`
  prints the learned thresholds, rejection counts and per-horizon summary into
  the **job log** as well as the artifact. Entry 003's metrics were unreadable
  because artifact blob storage is blocked by egress policy from the analysis
  context; a result that cannot be read cannot be judged, so the numbers now
  travel in the log too.
- **Verification before pushing**: 12 new unit tests plus the full existing
  suite — **201 passed**, `compileall` clean, request JSON and workflow YAML
  both parsed and asserted (7 steps, correct runner labels, correct path
  filter).
- **Result**: **CODE_READY — AWAITING GOVERNED RUN.** No performance claim is
  made. Nothing has been measured against real data yet; the December run's
  numbers will decide whether this shape is worth anything, and the December
  F01–F06 table in Entry 004 is the failure control it must be read against —
  especially F05A SESSION_OPEN_RECOVERY, the worst standalone component and the
  closest existing analogue to this lane's decline-then-stabilise framing.
- **Still open / not claimed**: Entry 003's v1 run metrics remain UNAVAILABLE;
  this lane is still unregistered in Drive governance; validation on Jan/Feb
  2025 with frozen thresholds has not been requested; March 2025 untouched and
  fail-closed in both the module and the workflow guard.
- **Paths**: `src/a1clean/formula_research/claude_mg_intraday_v2.py`,
  `tests/test_claude_mg_intraday_v2.py`,
  `claude-mg-intraday-v2-requests/current.json`,
  `.github/workflows/claude-mg-intraday-v2.yml`.

---

## Entry 006 — 2026-09-16 — V2 EXECUTED on December 2024. Result: FAIL on discovery. Does not beat the existing baseline.

First Claude-lane entry carrying real measured numbers, read directly from the
job log (not the artifact, not the green tick).

- **Run**: `35089709020`, job `104772866508`, workflow
  `.github/workflows/claude-mg-intraday-v2.yml`, commit
  `f96ff85299644558b2f819ac484924f556b1bd2c`. Runner `A1-WINDOWS-COMPUTE`
  (`[self-hosted, windows, x64, a1-clean-parity]`). Queued 11:19:41Z, started
  11:50:49Z once the runner came online, module ran 11:51:30Z → 12:01:10Z
  (9m40s), conclusion `success`. Artifact `10445226948`. Guards all passed:
  request schema, authorization phrase, March-refusal, Drive binding, and the
  full 201-test suite green **on the runner**.
- **Source**: `Raw Des 02-31-2024.csv`, 936 tickers, phase `discover`,
  `precursor_window_days=8`, horizons `5,15,30,60` regular bars,
  `min_streak_grid=1..5`. `future_data_used_for_candidate_state: false`,
  `winner_only_filter_used: false`.
- **Learned thresholds (frozen)**: `dormant_return_cutoff_pct=-1.6949`,
  `flow_persistence_cutoff_ratio=0.92989`, `min_absorption_streak_days=4`
  (grid-selected), `chg_chase_cutoff_pct=3.3210`, `close_location_cutoff=0.4`,
  `min_day_trade_value=206,853,500`, `tp1_vol_multiple=0.19607`,
  `tp2_vol_multiple=0.39651`.

### Measured outcome by min_streak (signals / mean forward return % / positive rate)

| min_streak | signals | tickers | dates | 5b mean / pos | 15b mean / pos | 30b mean / pos | 60b mean / pos |
|---|---|---|---|---|---|---|---|
| 1 | 563 | 262 | 10 | −0.266 / 21.98% | −0.294 / 23.66% | −0.375 / 26.62% | −0.453 / 26.48% |
| 2 | 346 | 186 | 9 | −0.338 / 19.70% | −0.288 / 24.67% | −0.307 / 26.92% | −0.360 / 26.27% |
| 3 | 203 | 123 | 8 | −0.345 / 20.71% | −0.261 / 26.34% | −0.379 / 30.29% | −0.347 / 28.28% |
| 4 | 109 | 73 | 7 | −0.217 / 22.64% | −0.049 / 28.57% | −0.154 / 34.41% | −0.049 / 28.40% |
| 5 | 50 | 33 | 6 | −0.045 / 29.17% | **+0.161** / 29.55% | **+0.119** / 42.50% | **+0.038** / 27.78% |

### Verdict against the governed bar — FAIL

`CLAUDE.md` states a formula near 55–59% positive rate with negative Q25 is not
a high-quality MG answer. This candidate is far below that bar:
**`forward_q25_pct` is negative in every single cell of the grid**, and
`forward_q50_pct` is exactly `0.0` in many cells — the median signal produces
no price move at all.

Head-to-head against the GPT lane's December baseline on the **same source**
(Entry 004; their means converted from fraction to percent):

| | 5 bars | 60 bars |
|---|---|---|
| F02A SELL_RESILIENCE | **+0.094% / 32.03%** | −0.016% / 35.60% |
| F01A BUY_STALL | −0.133% / 21.42% | −0.161% / 30.86% |
| F05A SESSION_OPEN_RECOVERY | −0.498% / 16.93% | −0.456% / 26.27% |
| **Claude v2, streak=4 (learned)** | −0.217% / 22.64% | −0.049% / 28.40% |

At the grid-selected `min_streak=4`, v2 is **beaten decisively by the simple
standalone F02A SELL_RESILIENCE** on both mean return and positive rate at 5
bars, is roughly level with F01A BUY_STALL, and only clearly beats F05A — the
worst component in the corpus. A candidate combining a multi-day precursor, an
intraday ignition and ten failure gates that cannot beat one standalone
component is not carrying its complexity.

### The one genuine lead: dose-response with streak length

Mean forward return improves monotonically with `min_streak` at the longer
horizons — 15 bars: −0.294 → −0.288 → −0.261 → −0.049 → **+0.161**; 60 bars:
−0.453 → −0.360 → −0.347 → −0.049 → **+0.038**. That is the direction H12
predicted, and it is the only encouraging structure in the run.

**It is not yet evidence.** It is confounded with shrinking sample: streak=5
rests on 36–48 evaluable events across **6 dates**. Nothing may be concluded
from that, and it is explicitly NOT treated as a result here.

### Three design defects this run exposed (mine, not the data's)

1. **TP multiples are learned from the wrong population.** `tp1_vol_multiple`
   came out at 0.196 — targets sit roughly a fifth of one daily range above
   price, far too close to be a real trader objective. The multiples are
   quantiles of the MFE distribution over *every* snapshot bar, which is
   dominated by do-nothing bars, instead of over *qualifying signals*. This
   also makes `tp1_hit_rate` (~50% at 60 bars) near-tautological rather than
   independent evidence, so **no TP hit-rate in this entry should be read as
   performance**.
2. **Date coverage is only 6–10 of December's ~20 trading days.** The
   8-day precursor window plus the streak walk-back mean no signal can fire
   before roughly day index 9, so half the month is structurally unreachable.
   Discovery is effectively running on half a month.
3. **The conjunction is lopsided.** `absorption_streak_too_short` accounts for
   493k–650k rejections against tens of thousands for every intraday gate
   combined. The precursor does ~95% of the filtering; the intraday ignition
   is a light touch on top, not the balanced conjunction the design intended.
   `no_remaining_room` (2–65) and `unstable_path` (13–313) are nearly inert.

- **Result**: **FAIL on discovery.** No promotion, no validation run, no
  Telegram anything. Thresholds are frozen in the artifact but must NOT be
  replayed on Jan/Feb as they stand — spending governed validation data on a
  candidate with a known-broken target derivation would waste the untouched
  period.
- **Next step, in order**: (a) re-derive TP multiples from the qualifying-signal
  MFE distribution and re-run discovery; (b) shorten or stagger the precursor
  window so the whole month is reachable; (c) test the streak dose-response as
  its own hypothesis on a longer span, since one month cannot separate it from
  small-sample noise; (d) treat F02A SELL_RESILIENCE as a component to
  incorporate rather than a rival to beat — it is the only standalone signal in
  the corpus pointing the right way.
- **Paths**: run
  `https://github.com/DontAsk3010/a1-clean-orchestration/actions/runs/35089709020`;
  artifact `claude-mg-intraday-v2-35089709020` (ID `10445226948`);
  `src/a1clean/formula_research/claude_mg_intraday_v2.py`.

---

## Entry 007 — 2026-09-16 — Owner-posed hypotheses H13/H14 built: open extremes and rung escalation

Owner directed two concrete claims to be tested against real market data rather
than argued: does `Open == Low` reliably resolve up (and `Open == High` down),
and does strength escalate in rungs — 3.5% confirming 5%, then 5% pushed
through 5.7% confirming 12%.

- **Module**: `src/a1clean/formula_research/claude_open_extreme_ladder_v1.py`,
  8 unit tests, full suite **209 passing**, `compileall` clean.
- **Two methodological decisions that determine whether this can be a formula
  at all**:
  1. **`Open == Low` is split into two separate measurements.** The hindsight
     form (open equals the day's *final* low) is knowable only after the close;
     it is a research label and the Master's causality contract forbids it as an
     executable input. The causal form (at this snapshot price has never traded
     below the open) is knowable live at every 5-minute slot and is the only
     tradable reading. Conflating the two would manufacture an edge that cannot
     be traded, so the output labels them explicitly and never merges them.
  2. **Every conditional is reported beside the unconditional full-universe
     baseline, with lift in percentage points.** The question asked was "is it
     *sure* to go up" — that can only be answered as a probability against the
     base rate. A 60% up-rate is worthless if the universe runs at 59%.
- **Degenerate-day control**: a ticker-day with `high == low` satisfies
  `Open == Low` trivially while representing no trading at all. These are
  counted and excluded, and the excluded count is published so the exclusion is
  visible rather than silent.
- **Ladder design**: rungs are measured against the **previous day's close**, matching
  the CHG% the MG output contract publishes. The ladder is deliberately denser
  than the owner's cited rungs — `1,2,3,3.5,4,5,5.7,7,10,12,15,20,25` — so that
  a genuine step shows up as a break in the curve rather than being assumed by
  only sampling the levels the hypothesis names. Measured both unconditionally
  and conditioned on a **strong cross** (crossing bar closes in the upper half
  of its own range with value expansion against prior bars), which is the
  operational reading of "kuat tembus" and is judged only at the crossing bar so
  no forward information enters the condition. Retention
  (`P(close at or beyond rung | reached)`) separates a level that holds from one
  merely touched. Mirror ladder measured downward.
- **Why this also matters for Entry 006's broken targets**: if rung transition
  probabilities sit materially above base rate, the rungs are behavioural levels
  the market respects, and TP-1/TP-2 can be derived from them. That is a
  market-derived target in the sense Master §20A.6 demands, and a far better
  replacement for the quantile-of-MFE derivation that Entry 006 found produced
  trivially close targets.
- **Result**: **CODE_READY — AWAITING GOVERNED RUN.** No claim is made about
  either hypothesis. They may well fail; the December numbers decide.
- **Paths**: `src/a1clean/formula_research/claude_open_extreme_ladder_v1.py`,
  `tests/test_claude_open_extreme_ladder_v1.py`,
  `claude-mg-open-extreme-ladder-requests/current.json`,
  `.github/workflows/claude-mg-open-extreme-ladder.yml`.

---

## Entry 008 — 2026-09-16 — H13/H14 EXECUTED on December 2024. Open-extremes: FAIL as tradable. Ladder: PARTIAL, with one real structural find.

- **Run**: `35097581002`, job `104798657443`, commit `bdc6af7`, runner
  `A1-WINDOWS-COMPUTE`, module ran 12:47:38Z → 12:52:02Z (4m24s), conclusion
  `success`, artifact `10446918822`.
- **Scope**: `Raw Des 02-31-2024.csv`, 900 tickers, 15,201 ticker-days seen,
  **13,127 evaluated, 2,074 degenerate flat days excluded** (13.6% of the month
  is untraded-flat — a large share, and they would have silently inflated the
  `Open == Low` result had they been left in).
- **Unconditional baseline**: `P(close > open) = 35.03%`,
  `P(close > prev close) = 36.18%`, median day return `0.00%`.

### H13 — Open == Low / Open == High → FAIL as a tradable pattern

| | n | P(close>open) | P(close>prev close) | mean day return |
|---|---|---|---|---|
| baseline | 13,127 | 35.03% | 36.18% | +0.02% |
| **open == low** (hindsight) | 2,363 | 83.92% (**+48.89pp**) | 61.57% (**+25.39pp**) | +2.09% |
| **open == high** (hindsight) | 3,674 | 0.00% (−35.03pp) | 13.26% (−22.93pp) | −1.45% |

**The headline lift is largely an artifact of the definition.** If the open IS
the day's final low then `close >= open` is true by construction, so the 83.92%
is near-tautological — the missing 16% is only ties where close equals open.
`Open == High` giving exactly `0.00%` proves the same point from the other side.
Reporting +48.89pp as a discovery would be self-deception.

The non-tautological number is `P(close > prev close)`: **61.57% vs 36.18%
baseline, +25.39pp**. That is real — a gap-down day can open at its low and
still close under the prior close — but it is still **hindsight**: you only know
the open was the final low after the close.

**The decisive test is the causal form, and it does not survive it:**

| executable state | snapshots | outcome |
|---|---|---|
| `low_so_far == open` | 215,227 | `P(close > price now)` = **34.33%** |
| `high_so_far == open` | 298,765 | `P(close < price now)` = **37.92%** |

At 34.33%, the tradable version of "Open == Low" is **at or slightly below** the
35.03% daily base rate. **There is no edge in the form that can actually be
traded.** The answer to "is Open == Low sure to go up" is **no**.

**Instrumentation gap, stated rather than hidden**: the exact unconditional
`P(close > price at snapshot t)` was not computed, so the 35.03% daily figure is
a proxy rather than a matched baseline. The conclusion is robust to this (34.33%
is nowhere near a level that would survive a stricter comparison) but the
matched baseline should be added before this is cited as settled.

### H14 — Rung escalation → PARTIAL. The owner's specific chain is not confirmed.

`P(reach next rung | reached)` upward, with `n` reached:

| rung → next | p | n | strong cross | retention |
|---|---|---|---|---|
| 1 → 2 | 65.7% | 7,747 | 72.5% | 42.8% |
| 2 → 3 | 70.2% | 5,093 | 74.2% | 40.2% |
| 3 → 3.5 | 85.3% | 3,576 | 88.7% | 39.6% |
| **3.5 → 4** | **87.8%** | 3,051 | 89.8% | 39.3% |
| 4 → 5 | 78.5% | 2,679 | 81.7% | 37.9% |
| **5 → 5.7** | **85.2%** | 2,104 | 86.4% | 37.4% |
| 5.7 → 7 | 75.8% | 1,793 | 79.2% | 37.8% |
| **7 → 10** | **49.9%** | 1,359 | 57.5% | 36.4% |
| 10 → 12 | 72.1% | 678 | 79.8% | 34.7% |
| 12 → 15 | 69.9% | 489 | 73.2% | 34.4% |
| 15 → 20 | 62.6% | 342 | 66.0% | 35.7% |
| 20 → 25 | 43.9% | 214 | 43.0% | 38.3% |

**Chaining the owner's claims:**
- "breaks 3.5% → confirms 5%" = 0.878 × 0.785 = **68.9%**. Better than a coin
  flip, but not a confirmation.
- "5% strong through 5.7% → confirms 12%" = 0.758 × 0.499 × 0.721 = **27.3%**.
  **Not supported — roughly one in four.**

**Two confounds that inflate every number in that table, both mine:**
1. **Rung spacing is uneven.** `3 → 3.5` is a 0.5pp step while `7 → 10` is 3pp.
   The high probabilities at the tight rungs are substantially a spacing
   artifact, so the columns are not comparable as they stand.
2. **`median_bars_to_next_rung = 0.0` at almost every rung.** The next rung is
   typically reached **in the same bar**. This is therefore not step-by-step
   confirmation over time — it is one impulse bar spanning several rungs at
   once, and the conditional probability is inflated by within-bar
   co-occurrence. This substantially weakens the escalation reading as stated.

**The one genuine structural find**: there is a real trough at **7 → 10
(49.9%)** that then *recovers* at 10 → 12 (72.1%). Uneven spacing explains part
of it, but not the recovery — a 3pp step at 12 → 15 scores 69.9% while the same
3pp step at 7 → 10 scores 49.9%. So the 7–10% band behaves as a genuine
resistance zone, and past ~10% continuation improves markedly. The downward
ladder is asymmetric there (7 → 10 down = 38.2%), i.e. upside continuation past
7% is stronger than downside. This is non-obvious and worth pursuing.

**Retention is the trading-relevant constraint**: `P(close at or beyond rung |
reached)` sits at **34–43% at every single rung**. Levels get touched and mostly
not held. Any TP built on these rungs must be taken intraday on touch; holding
to the close discards roughly two-thirds of it.

- **Result**: **H13 FAIL (no tradable edge). H14 PARTIAL — the specific chain is
  not confirmed, but the 7–10% resistance band and its asymmetry are real
  findings.**
- **Usable output despite the partial result**: the transition table is a
  market-derived TP ladder. From +3.5%, TP-1 = 4% (~88% touch) and TP-2 = 5%
  (~69% touch) are grounded in measured behaviour, which is what Master §20A.6
  requires and what Entry 006's quantile-of-MFE derivation failed to deliver.
- **Next**: re-run the ladder on **evenly spaced rungs** to remove the spacing
  confound, and add a **same-bar vs later-bar split** so genuine sequential
  confirmation is separated from single-impulse co-occurrence. Add the matched
  snapshot baseline for the causal open-extreme comparison. Only then is either
  hypothesis settled.
- **Paths**: run
  `https://github.com/DontAsk3010/a1-clean-orchestration/actions/runs/35097581002`;
  artifact `claude-mg-open-extreme-ladder-35097581002` (ID `10446918822`);
  `src/a1clean/formula_research/claude_open_extreme_ladder_v1.py`.

---

## Entry 009 — 2026-09-16 — MG output contract rendered from real signals; full-month daily feed built

### Part A — the contract rows exist now, from real December signals

Run `35098274931` (commit `5ee8bcf`) completed `success`; module 13:06:24Z →
13:15:34Z, render step 13:15:34Z → 13:15:35Z, artifact `10447967070`.
**109 real signals** across 97 snapshot slots rendered into
`CODE | PRICE | CHG% | TP-1 | TP-2`. Sample, verbatim from the job log:

```
[2024-12-20 09:02:00]  (5 ticker)
AMMN | 9.000 | +1.98% | 9.053 | 9.107
BBNI | 4.340 | +0.93% | 4.363 | 4.386
BMRI | 5.750 | +1.32% | 5.774 | 5.799
BRIS | 2.680 | +1.52% | 2.694 | 2.708
TLKM | 2.550 | +1.19% | 2.563 | 2.577
```

**The rendered rows are themselves evidence of Entry 006's failure.** SMGA
publishes at price 54 with TP-1 also 54 — a target identical to the entry price.
AMMN's TP-1 is +0.59%. These are the direct consequence of
`tp1_vol_multiple = 0.196` being learned from the unconditional bar pool. The
pipeline is proven end to end; the targets it carries are not usable.

### Part B — two structural facts the real output exposed

1. **The governed source is minute-resolution, not 5-minute.** Observed
   timestamps are `09:04`, `09:07`, `11:29`, `13:42` — not on 5-minute
   boundaries, consistent with the `*_1M` physical field names. Any MG feed must
   therefore evaluate at native bar resolution and *assign* each qualifying bar
   to the 5-minute slot containing it. Publishing raw bar timestamps as if they
   were slots would misstate the contract.
2. **The discovery module cannot produce a feed.** It keeps only the first
   qualifying snapshot per ticker-day — correct for outcome statistics, wrong
   for a feed, where a ticker republishes at every slot while it still
   qualifies. These are opposite emission policies and cannot be the same code
   path.

### Part C — `claude_mg_daily_feed_v1` built to answer the actual question

New module reproduces the live emission policy for a whole source month: per
date, per 5-minute slot, which tickers would have been published. It imports the
state and gate functions from `claude_mg_intraday_v2` unchanged, so the feed can
never drift from the researched candidate — only the emission policy differs.

- Within one slot a ticker appears once, carrying its latest qualifying state.
- **Pre-open**: rows before the day's first regular-session bar carrying neither
  session flag are counted and reported with their earliest observed times, as
  evidence of what the source holds. They are **not published** — the MG
  contract begins at the first automatic snapshot, and these gates were never
  researched against pre-open mechanics. What the source carries and what the
  contract publishes are different questions and are not conflated.
- `--from-time` is a **display filter only** and never filters evaluation, per
  the Master's no-universal-cutoff rule.
- 7 new tests (slot flooring at 09:04→09:00, 09:07→09:05, 11:29→11:25; pre-open
  detection excluding the midday break; malformed timestamps; display filter
  isolation). Full suite **224 passing**, `compileall` clean.

- **Result**: **CODE_READY — AWAITING GOVERNED RUN.** Expect the feed to be
  sparse and empty on many December dates: the candidate produced only 109
  first-appearances all month and failed its outcome test. A feed from a failing
  formula shows what it would have published, not that it should have.
- **Paths**: `src/a1clean/formula_research/claude_mg_daily_feed_v1.py`,
  `tests/test_claude_mg_daily_feed_v1.py`,
  `claude-mg-daily-feed-requests/current.json`,
  `.github/workflows/claude-mg-daily-feed.yml`.

---

## Entry 010 — 2026-09-16 — Full-month feed executed; Open=Low scout + ignition built to chase the 10% question

### Part A — feed result (run `35101362991`, artifact `10448976786`)

936 tickers, **19 trading dates in source, only 7 produced any publication**,
5,397 qualifying bars. Per-day:

| date | slots | tickers |
|---|---|---|
| 12-18 | 54 | 4 — BBYB, BIRD, CMRY, TCPI |
| 12-19 | 13 | 2 — CTRA, PALM |
| 12-20 | 50 | 14 |
| 12-23 | 64 | 26 |
| 12-24 | 64 | 21 |
| 12-27 | 52 | 14 |
| 12-30 | 64 | 28 |

**Dec 2–17 published nothing at all.** This is Entry 006 defect #2 confirmed
concretely: the 8-day precursor window plus the streak walk-back make the first
third of the month structurally unreachable. A feed that is silent on 12 of 19
days is not a usable feed.

**Pre-open exists and is now quantified**: 6,918 rows, exactly **one row per
ticker-day**, present on **all 19 dates**, earliest observed **08:58–08:59**.
Counted as source evidence, not published — the contract starts at the first
automatic snapshot and these gates were never researched against pre-open
mechanics.

### Part B — owner's construction, and why the Entry 008 null does not refute it

Owner supplied a target report format and a sharper research question: use
Open=Low as a **scout**, raise a signal only once the ticker is *also* already
up meaningfully on the day, and find the tickers genuinely strong enough to
carry past **+10%**.

**Entry 008's null result was for `Open == Low` ALONE** (causal form 34.33%
against a 35.03% base rate). That stands. But `scout AND chg >= X` is a
different conditional, and nothing measured so far speaks to it. Treating the
solo null as refuting the combined form would be a reasoning error, so the
combination is tested rather than dismissed.

New module `claude_mg_openlow_strength_v1`:

- **Scout**: causal `low_so_far >= day_open` — price has never traded below the
  open up to this bar. Degenerate `high == low` days excluded and counted.
- **Ignition**: first bar where the scout holds *and* `chg >= min_chg_pct`
  (default 3.5%). One signal per ticker-day, matching the requested report.
- **Targets are ladder rungs, not volatility quantiles.** TP-1/TP-2 are the next
  two rungs above the current change on the measured ladder from Entry 008
  (3.5/5/5.7/7/10/12/15/20/25). This directly replaces the derivation that
  produced Entry 009's TP-1 equal to its own entry price.
- **The 10% question is its own labelled outcome**, not a distant target:
  `reached_10pct` is recorded per signal, and the reached group is contrasted
  against the rest on features observable **at signal time only** — change at
  signal, bar index, value expansion, close location, day range so far,
  prior-day range. A separation there is a *lead* for a stricter gate; the
  module does not assume one exists.
- Two reports emitted: the full replay in the owner's format, and a
  strength-only report containing just the ≥10% signals.
- Causality enforced: scout and ignition read bars `0..t` plus the prior close;
  target hits and the 10% label read only bars after `t`, same date, and never
  re-enter a gate. Unit-tested that a wild future bar cannot alter signal-time
  features.

- **Result**: **CODE_READY — AWAITING GOVERNED RUN.** 12 new tests, full suite
  **236 passing**, `compileall` clean. No claim is made about whether the
  combined scout+ignition carries an edge, nor about what fraction reaches 10%.
- **Paths**: `src/a1clean/formula_research/claude_mg_openlow_strength_v1.py`,
  `tests/test_claude_mg_openlow_strength_v1.py`,
  `claude-mg-openlow-strength-requests/current.json`,
  `.github/workflows/claude-mg-openlow-strength.yml`.

---

## Entry 011 — 2026-09-16 — Open=Low scout + ignition EXECUTED. A real discriminator for the 10% question found.

First run `35103189036` **FAILED** — it completed the full analysis in 3m31s and
then died on `print`: the runner's cp1252 stdout cannot encode the report's
emoji, so a finished analysis was discarded by a console codec. Fixed by writing
reports to disk before printing and degrading instead of raising. Recorded
because a failure caused by my own output formatting is still a failure.

Re-run `35104707504` (commit `e81a41e`), module 13:52:48Z → 13:56:14Z (3m26s),
`success`, artifact `10450456275`.

### Ungated result — Open=Low scout + chg ≥ 3.5%

| metric | value |
|---|---|
| signals | 1,246 |
| TP-1 hits | 520 (41.7%) |
| TP-2 hits | 398 (31.9%) |
| reached ≥10% | **281** |
| **P(reach 10% \| signal)** | **22.55%** |

Targets are now real: rung-based TP-1/TP-2 sit at genuine ladder levels rather
than the +0.6% artefacts of Entry 009. The owner's complaint about short targets
is addressed by construction.

### The discriminator — this is the answer to "which ones are strong to 10%"

Features measured **at signal time only**, reached-10% group vs the rest:

| signal-time feature | reached ≥10% (n=281) | did not (n=965) | separation |
|---|---|---|---|
| **mean bar index** | **7.83** | 15.56 | **fires at half the elapsed time** |
| **mean chg at signal** | **8.32%** | 5.41% | **+2.91pp** |
| **mean prior-day range** | **8.61%** | 5.88% | **+2.73pp** |
| mean day range so far | 6.38% | 4.58% | +1.80pp |
| mean value expansion | 226.6 | 190.0 | +36.6 |
| mean close location | 0.895 | 0.924 | **none — slightly inverted** |

Three features separate materially and one does not. The tickers that carry past
10% **fire early in the session**, are **already strong when signalled**, and —
the genuinely useful one — **were already volatile the previous day**, which is a
prior-day fact knowable before the session even opens.

**Close location does not separate** (0.895 vs 0.924, mildly the wrong way) and
is therefore deliberately NOT gated on, despite being intuitively appealing.
Gating on it would have cost signals and bought nothing.

### Next run: the gates applied

`min_chg_pct 7.0`, `max_bar_index 10`, `min_prior_day_range_pct 7.0`, pushed as
request `..._GATED`. **These are mean differences, not a validated filter.** The
question the gated run answers is whether `P(reach 10% | signal)` rises
materially above the 22.55% ungated baseline and what it costs in signal count —
a gate that triples precision while leaving two signals a month is not useful.

- **Result**: **MEASURED — DISCRIMINATOR FOUND, GATE UNTESTED.** No claim that
  the gate works until the gated run reports.
- **Paths**: run
  `https://github.com/DontAsk3010/a1-clean-orchestration/actions/runs/35104707504`;
  artifact `claude-mg-openlow-strength-35104707504` (ID `10450456275`).

---

## Entry 012 — 2026-09-16 — GATED run: precision more than doubles. Best result of the lane so far, and still in-sample.

Run `35105451803` (commit `d5ca1eb`), module 13:59:42Z → 14:04:09Z (4m27s),
`success`, artifact `10450401781`. Gates applied: `min_chg_pct 7.0`,
`max_bar_index 10`, `min_prior_day_range_pct 7.0`.

| | ungated (`35104707504`) | **gated (`35105451803`)** |
|---|---|---|
| signals | 1,246 | **166** |
| TP-1 hits | 520 | 57 |
| TP-2 hits | 398 | 45 |
| reached ≥10% | 281 | **86** |
| **P(reach 10% \| signal)** | 22.55% | **51.81%** |

**Precision more than doubles, +29.3pp.** Signal volume lands at 6–12 per
trading day, which is a usable publication rate rather than a curiosity. The
surviving signals cluster before 09:15, exactly as the bar-index separator in
Entry 011 predicted — the gate is behaving the way the evidence said it should.

### Three things that stop this being a win yet

1. **It is in-sample.** The gate values were derived from December means and
   then tested on December. That is the textbook setup for overfitting. Nothing
   here is validated until the same frozen gates are replayed unchanged on
   Jan/Feb 2025. This is the single most important caveat in the entry.
2. **Recall is 30.6%.** 86 of the 281 ticker-days that reached +10% are caught;
   **two in three are missed**. Precision was bought with coverage.
3. **TP hit rates are NOT comparable across the two runs.** Gated signals fire
   at ≥7%, so their next rungs are 10% and 12% — materially bigger jumps than an
   ungated signal firing at 3.5% with rungs at 5% and 5.7%. The gated run's
   lower TP-1 rate (34.3% vs 41.7%) reflects harder targets, not worse
   behaviour, and reading it as a decline would be an error.

Also visible in the output: signals already above the top rung publish TP-2 as
`—` rather than inventing a level (POLU at +24.51%, XCIS at +22.64%). Absent
stays absent.

- **Result**: **STRONG IN-SAMPLE, UNVALIDATED.** No promotion, no claim of an
  edge until out-of-sample replay reports.
- **Next**: replay the **frozen** gates on `Raw Jan 01-31-2025.csv`. If
  P(reach 10%) holds near 50% there, the discriminator is real; if it collapses
  toward the 22.55% base, it was overfitting and this entry becomes a negative
  result. March 2025 remains untouched.
- **Paths**: run
  `https://github.com/DontAsk3010/a1-clean-orchestration/actions/runs/35105451803`;
  artifact `claude-mg-openlow-strength-35105451803` (ID `10450401781`).

---

## Entry 013 — 2026-09-16 — Telegram Sub-Sub Master read at last. Three output-contract errors found in my own work.

Owner challenged whether I actually understood the Telegram report contract.
I did not. Every report built in this lane so far took its format from a single
summary line in the Branch 07 handbook §3. The real output contract lives in
Branch 13, in **`00_A1_CLEAN_TELEGRAM_SUB_SUB_MASTER_HANDBOOK_ACTIVE_20260910`**
(Drive `1qmnjMH4q-8USALhndTz2CAGaGihD7Orhk9lcm-5HqbM`, `VERSION 20260910 V1`),
which Entry 003 recorded as unread and which I then failed to go read for ten
further entries. Now read in full to `END`.

### Error 1 — displayed time was the bar minute, not the publication slot

§4: *"For periodic snapshot outputs, displayed HH:MM is the governed
AS_OF/publication-slot identity."* §7: *"A signal may become true between
publication slots. The next Telegram snapshot publishes the latest validated
state; the slot time does not necessarily equal first-detectable signal time."*

Every report I produced showed raw bar minutes — `09:01`, `09:03`, `10:55`.
Fixed: rows now render the **5-minute slot**, while the JSON retains
`first_detectable_time` alongside `slot` so the distinction §7 draws is
preserved as evidence rather than collapsed.

### Error 2 — zero-match days were silently omitted

§7: a valid zero-match renders `========`, and *"must never disguise feed
failure, stale data, scanner failure, bridge failure or Telegram delivery
failure."*

The December feed (Entry 010) simply dropped the 12 dates that published
nothing. A reader could not distinguish "scan ran, genuinely nothing qualified"
from "the system was down" — precisely the confusion §7 forbids. Fixed: a day
with no qualifying rows now renders `========`.

### Error 3 — my own gate contradicts the MG definition

§6: *"'Early' in MULAI GENIT refers to development stage, not a fixed morning
clock."*

Entry 012's `max_bar_index 10` gate is empirically the strongest separator and
lifts precision to 51.81% — but it effectively turns MG into a morning-only
family, which the governing definition explicitly rejects. **Recording this
rather than keeping quiet because the number is good.** The separator is real;
the *implementation* as a clock gate is not contract-compliant. It should be
re-expressed as a development-stage condition (bars since the day's first
qualifying state, or progress achieved per unit of elapsed session) that
captures the same behaviour without imposing a clock. Until then the 51.81%
figure carries this caveat.

### Confirmed correct

`CODE | PRICE | CHG% | TP-1 | TP-2` (§6A), **no TP-3 in automatic MG** (§6A),
TP values not computed Telegram-side (§6A), no silent zero substitution (§3),
and availability distinct from value. Also newly learned and not yet used:
§6B–§6E give the other four Jalur A families their own distinct column
contracts (SIAP GAS adds ENTRY/SL/HOLD, MAU NGACIR adds ENTRY/SL, NGINTIP ARA
is `CODE | PRICE | CHG% | PRIO | SL`, MAU NEMPEL is `CODE | PRIO | PRICE | SL |
STATUS` with no TP at all).

- **Result**: **CONTRACT ERRORS CORRECTED (2 of 3).** Error 3 is a design
  conflict recorded openly, not silently retained.
- **Paths**: `src/a1clean/formula_research/claude_mg_openlow_strength_v1.py`,
  `tests/test_claude_mg_openlow_strength_v1.py`.

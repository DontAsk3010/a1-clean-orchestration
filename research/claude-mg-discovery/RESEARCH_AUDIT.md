# Claude MG Research Audit

Status: **PHASE 0 — AUDIT COMPLETE. No independent formula proposed yet.**
Branch: `research/claude-mg-discovery`
Prepared: 2026-09-15 (local commit; not yet pushed — see "Session blockers" at the end)
Scope target: Telegram A / EARLY_POTENTIAL / 👀 MULAI GENIT (MG)

This document is produced strictly from reading: the 8 governing Google Drive authority
documents (in the order CLAUDE.md specifies) plus the historical `004_MASTER_HANDBOOK`
export; the full git history of this repository across all branches (read-only, nothing
checked out or modified); every `*-requests/current.json` dispatch record; every
`plans/formula/*.json` and `plans/lane2/*.json`; the two frozen formula packs and their
evidence file; `docs/architecture.md` / `parity-contract.md` / `recovery-contract.md`;
and the Google Drive governed data-plane folder structure (manifests/indexes only — no
bulk raw data was downloaded). GitHub Actions run/job/artifact data via the REST API was
**UNAVAILABLE** from this sandbox (blocked at the sandbox network layer, independent of
whether the repo itself is public — see "Session blockers"). No new formula, threshold,
or numeric result in this document was invented; everything traceable is cited to a file
path or Drive doc.

---

## 0. Governing-authority precedence resolved for this audit

Reading the 8 Drive docs in CLAUDE.md's stated order surfaced a few things the repo's own
`CLAUDE.md` does not currently reflect. Recorded here so later work doesn't silently
re-litigate them:

- **Doc #7 is mislabeled in `CLAUDE.md`.** It is titled there as "Formula VNext authority"
  but its actual content (confirmed by its own text and by every cross-reference to it
  from the other docs) is the **Sub-Master Index / Router** — a table of contents, not a
  formula authority. There is no separate "Formula VNext" document among the 8; the
  closest thing is Master §20/§20A (formula governance framework) and doc #8's old
  Module A–N Colab contract. This audit treats doc #7 as the router it actually is.
- **Formula-candidate work is now authorized, as of today (2026-09-15).** Every doc
  except the newest Current-Execution entry (doc #2's top block) says formula/threshold
  work is CLOSED pending owner authorization. That newest entry is the authorization —
  but only for **candidate** construction/testing (a new family set called **F01–F06**:
  BUY_STALL, SELL_RESILIENCE, FRESH_STALE_HIGH, EARLY_STRENGTH_VS_LATE_LIFT,
  RECOVERY_RUNNER, PROGRESSIVE_H2_H1_PREPARATION). **Final/canonical/live promotion
  remains explicitly CLOSED.** This is consistent with CLAUDE.md's own framing of this
  branch as `RESEARCH_ONLY`.
- **Open question the project owner has not yet reconciled, and this audit will not
  guess at:** F01–F06 (opened today, Drive-side) and the existing MG-specific
  `telegram_mg_*` V3→V8d lineage (already running for a week in this repo, GitHub-side)
  are two different naming schemes with no stated mapping between them. CLAUDE.md's own
  brief to Claude is unambiguously about MG/EARLY_POTENTIAL specifically, so this audit
  and the hypothesis registry below stay scoped to MG — but the user/owner should decide
  whether F01–F06 is meant to explain MG (and the other four Telegram families) or is an
  independent track. **Flagged, not resolved, here.**
- **Git structural note:** `research/claude-mg-discovery` is a synthetic root import (its
  first commit `c4dc796` has no parent in this remote) carrying a full snapshot of the
  GPT lane's tree, not a descendant of the granular 300+-commit V3→V8d history. That
  granular history lives on `origin/formula/current-clean-research-v1`. Every commit
  hash cited below is from that branch (read via `git show`/`git log`, never checked
  out), not from this branch's own 2-commit log. As of this audit, this branch's tree is
  byte-identical to that branch's HEAD except for `CLAUDE.md` and the two files in this
  folder — i.e. no independent Claude research existed before this document.
- **Data semantics are stable and consistent everywhere checked** (Drive docs, repo
  `README.md`/`CLAUDE.md`, and the code in `formula_replay.py`): `RAW_Aux2` = physical
  slot for `TRADE_VALUE_1M`; `RAW_OpenInterest` = physical slot repurposed as
  `NBSS_VALUE_1M` (a signed net transaction-value imbalance proxy, **not** futures open
  interest, valid only where availability/mechanism-eligibility is proven);
  `HAKA_VALUE_1M = (TRADE_VALUE_1M + NBSS_VALUE_1M) / 2`;
  `HAKI_VALUE_1M = (TRADE_VALUE_1M − NBSS_VALUE_1M) / 2`. Missing/unproven data must be
  `UNKNOWN`/`UNAVAILABLE`, never zero. No document contradicts this.

---

## 1. Prior research actually tested

Everything below lives on `formula/current-clean-research-v1` (imported unchanged onto
this branch). All development happened in a single ~10-hour window on 2026-09-15
(19:15–05:20 the next morning, commit timestamps), each version's discovery/validation
corpus fixed to `Raw Des 02-31-2024.csv` (Dec 2024, discovery) → `Raw Jan 01-31-2025.csv`
+ `Raw Feb 03-28-2025.csv` (validation); **March 2025 is untouched OOS everywhere, no
exception found.**

- **Pre-V2 line — `telegram_mg_profit_qualified_v1.py`** (`MG_PROFIT_QUALIFIED_V1`,
  9 base candidates). Rejected wholesale: 2025-01-02 proof rejected all 9 candidates
  under executable profit-room gating (`plans/formula/telegram-mg-behavior-topology-v2.json`,
  `old_line_status`). Preserved, not deleted, per project rule.
- **V2 — `telegram_mg_behavior_topology_v2.py`** — six behavior topologies J01–J06
  (wake-response-retention, recovery-reclaim, compression-expansion,
  pullback-reaccel, flow-resilient-continuation, early-strength-retained), each a
  boolean AND of activity/range/path "wake" + up-path + persistence + acceptance +
  value-expansion + anti-stall/anti-late-lift components, TP1/TP2 = empirical quantiles
  (q25/q50 by default) of each topology's own prior-completed-dates reward history
  (walk-forward, `min_training_examples=30`). **Total structural failure** — see §2.
- **V3 — `mg_formula_family_v3.py` + `telegram_mg_structural_discovery_v3[_fast].py`**
  — direct response to V2's failure: 9 new formulas K01–K09 built as *transitions and
  consensus* over the same J01–J06 states (e.g. `K01_NEW_WAKE_RESPONSE = J01 and not
  seen_before(J01)`, `K08_MULTI_PATH_CONSENSUS = active_count≥2`) rather than new
  numeric thresholds — explicit `change_policy`:
  `STRUCTURAL_FAILURE_REQUIRES_COMPONENT_TOPOLOGY_REPLACEMENT_NOT_THRESHOLD_RESCUE_ONLY`.
- **V4 — `telegram_mg_sequence_discovery_v4.py`** — fixes one V3 parent,
  `K06_EARLY_RETAINED_FLOW`, then mines 1–3-marker *sequence signatures*
  (`NEW_x`/`HELD_x`/`HELD2_x`/`REGAIN_x`/`PREV_x`/`PRIOR3_x` over 8 boolean primitives +
  3 wake flags across successive 5-minute publications), requiring positive discovery
  Q25 and positive Q25 on **every** validation month. Produced the two frozen "V4 bridge"
  candidates (§6 below).
- **V5 — `telegram_mg_outcome_first_discovery_v5.py`** — drops the fixed-parent
  requirement entirely, mines from a much larger marker set (13 current-bar booleans + 6
  J-states + sequence markers + time-of-day band) up to 3-way, across the **full
  universe** with one discovery-representative event chosen per ticker-day. Directly
  answers the V4 evidence file's own recommendation to hunt for a failure discriminator.
  Introduces `outcome_path_quality.py` (net MFE, pre-peak MAE, first-positive-offset,
  reward/adverse ratio, retained-fraction) used by every later version.
- **V6 — `telegram_mg_trajectory_contrast_v6.py`** — first version to explicitly
  contrast a winner representative against a matched **near-twin failure** per
  ticker-day, across 4 outcome-quality families (FAST_CLEAN, STRONG_RUNNER,
  RETAINED_WINNER, ANY_POSITIVE), allowing both required *and* forbidden markers, and
  requiring discovery precision to beat the naive base rate before mining.
- **V7 — `telegram_mg_high_conviction_v7.py`** — narrows V6 to 3 flow-branded
  "HAKA_*" families using stricter discovery thresholds (top-quartile-of-positives
  q75/q85 rather than q50/q65 of all events). Superseded same day by V8/V8c
  (`superseded_by: A1_TELEGRAM_MG_MULTI_HYPOTHESIS_V8C_RESULT_V1`), with no numeric
  failure reason recorded — the practical reason is V7 still mines only the same J-state
  marker vocabulary V3–V6 used, while V8 opens an entirely new continuous multi-day
  feature space.
- **V8 / V8b / V8c / V8d — `telegram_mg_multihypothesis_v8{,b,c,d}.py`** — the first
  version implementing CLAUDE.md's full multi-day continuous-precursor list: windows
  w∈{2,3,5,8,10} trading days, computing sideways-ness, range/median-range, effort
  efficiency, close-location, value/volume trend ratio, NBSS buildup, pullback-from-peak,
  prior-peak-gain, range-contraction (3-day), value-vs-price effort, low-recovery-from-
  shakeout; current-day ignition ratios/accelerations for value, volume, range, path,
  close-location, NBSS. **V8 and V8b both have a real, confirmed runtime bug** —
  `CandidateParams()` is called with zero arguments against a frozen dataclass with 7
  no-default fields (`telegram_mg_multihypothesis_v8.py:396`,
  `..._v8b.py:252`) — neither could have executed to completion as committed. **V8d**
  (commit `3cecc74`, 68 lines) fixes this with a parameter factory; two immediate re-runs
  confirm the fix was load-bearing. V8c (independent of the bug) adds strict
  manifest-accounting cross-validation between the raw and semantic-bundle manifests.

**Run-frequency evidence** (from `git log` commit counts touching each `*-requests/`
directory on the formula branch): `mg-frozen-replay-requests` (8, most-iterated — a
targeted-replay fixture, e.g. exact expected TNCA/BMRI/CTRA snapshot prices for
2024-12-04), `telegram-mg-multihypothesis-v8-requests` (5, the V8→V8d iteration),
`telegram-mg-structural-discovery-v3-requests` (3, including one cancelled/re-run after
a causal-bug fix), `telegram-mg-replay-requests` (2), `telegram-mg-behavior-topology-v2-
requests` (2), all other MG directories (1 each). No directory was found empty.

---

## 2. Failed approaches and evidence-backed reasons

1. **V2 behavior-topology line — total, quantified structural failure.**
   `plans/formula/mg-v2-structural-failure-decision-20260915.json`
   (run `34968184620`, revision `012018b`, corpus Dec2024+Jan2025+Feb2025):

   | Topology | Raw candidates | Qualified |
   |---|---|---|
   | J01 wake-response-retention | 4,717 | **0** |
   | J02 recovery-reclaim | 1,536 | **0** |
   | J03 compression-expansion | 2,266 | **0** |
   | J04 pullback-reacceleration | 9,057 | **0** |
   | J05 flow-resilient-continuation | 6,503 | **0** |
   | J06 early-strength-retained | 2,254 | **0** |

   Quoted verbatim: *"All six broad behavior topologies produced zero candidates
   surviving the conservative prior-only profit-room gate across the development
   corpus. This is treated as structural failure of the tested component combinations,
   not as permission to rescue the result by repeatedly moving numeric thresholds."*
   Decision: replace the topology structures in V3, do not threshold-rescue V2. This run
   post-dates the pullback-detection bugfix (`d53de6f`), so the zero result is not an
   artifact of that known bug. One methodological caveat worth carrying into new work:
   the profit-room gate requires 30 walk-forward training examples per topology before a
   candidate can even qualify, which may have starved genuinely early-period signal —
   worth re-checking if a similar zero-qualified result recurs.
2. **Pre-V2 line (`MG_PROFIT_QUALIFIED_V1`) — rejected wholesale**, all 9 candidates,
   2025-01-02 proof, no candidate JSON survives in-repo (only the rejection is recorded
   as text).
3. **V4's own frozen candidate fails its own strict bar.**
   `formula-research/mg-candidates/MG_RR_FLOW_RENEW_V4.evidence.json` (run
   `34988412088`): Dec discovery n=22, positive-rate 72.7%, Q25 +0.005%, median +0.68%;
   Jan n=25, positive-rate 52.0%, **Q25 −0.589%**, median +0.009%; Feb n=53, positive-rate
   56.6%, **Q25 −0.742%**, median +0.459%. `strict_q25_cross_period_pass: false`.
   Verbatim: *"CORE_SEQUENCE_REPEATS_WITH_POSITIVE_MEDIAN_BUT_FAILURE_TAIL_REMAINS;
   KEEP_AS_BRIDGE_PARENT_FOR_V5_FAILURE_DISCRIMINATOR_DISCOVERY"*. This positive-median/
   negative-Q25 pattern — i.e. a real, repeating precursor sequence with a fat losing
   tail nobody has yet characterized — is the single most concrete, evidence-backed
   open problem in the whole corpus and is the direct basis for hypothesis **H05** below.
4. **Session-boundary contamination bug, found and guarded (not deleted).**
   `telegram_mg_precision_study.py:113-123`: the original `MG_B` causal lookback could
   pull prior bars from a different regular-session segment (i.e. mixing session-1 and
   session-2 history). The P0–P5 precision grid exists specifically to add a
   `session_safe` guard on top of the contaminated original logic — this is a
   data-quality/regime-mixing defect, not a hindsight leak, but it was not verified
   to be absent from other lookback-based features (multiday_context, pullback_reaccel).
   See **H10**.
5. **V8/V8b runtime defect** — see §1, fixed in V8d (`3cecc74`). Two immediate re-runs
   confirm the fix was necessary to get any output.
6. **V7 superseded** same-day by V8/V8c with no numeric reason recorded in-repo —
   inferred reason is methodological narrowing (same marker vocabulary as V6) rather
   than a documented quantitative failure.

---

## 3. Rich data dimensions underused so far

- **Canonical VWAP is structurally dead code, everywhere, in every version.**
  `formula_replay.py:108` hard-codes `"canonical_vwap": None` for every bar; no code
  path in the repo ever binds it to a real field. `F02B_SELL_RESILIENCE_ACCEPTANCE_
  RENEWAL` and `F05B_CANONICAL_VWAP_RECOVERY` have therefore never once evaluated to
  `TRUE` in any run. Confirmed independently by
  `plans/formula/telegram-family-feature-availability-v1.json`:
  `"CANONICAL_VWAP": "OPTIONAL_UNAVAILABLE_IN_CURRENT_RAW_SCOPE..."`.
- **`volume` is parsed everywhere but never load-bearing through V7.** Every version
  reads `RAW_VOLUME` into every bar; V8/V8b compute `pre{w}_volume_trend_ratio`,
  `cur_volume_accel_5v5`, `ign_volume_ratio` — but none of J01–J06, MG_A–H, or the P0–P5
  precision grid ever reference volume; only `trade_value` (IDR turnover) and `nbss`
  drive the causal formulas through V7. Given many IDX tickers trade at very different
  price levels, a raw-share-count-based ignition signal could carry independent
  information from a value-based one and has essentially never been tested on its own.
- **The independent algorithmic pattern-discovery lane
  (`src/a1clean/pattern_discovery/`) is completely disconnected from MG formula work.**
  It runs Ruptures (Pelt, change-point segmentation), STUMPY (matrix-profile
  motif/discord discovery), and DTW distance over `RAW_CLOSE`/`RAW_VOLUME`, but its own
  code declares `INDEPENDENCE_ASSERTIONS = {"formula_stage_opened": False, ...}` and it
  has never been wired into any MG discovery driver. Matrix-profile motif discovery in
  particular is directly relevant to CLAUDE.md's "quiet period followed by activity
  wake" and "any other recurring precursor" hypotheses, and to date nobody has applied
  it there. See **H03**.
- **Repeated close-location/acceptance is only ever a single-bar primitive.**
  `BAR_ACCEPTANCE = close ≥ (high+low)/2` and `cur_close_location` exist, but no version
  computes a *repeated-over-N-bars* acceptance count or streak. CLAUDE.md explicitly
  lists "repeated close-location/acceptance behavior inside a range" as a hypothesis to
  test; no code currently answers it. See **H01**.
- **"Progressive higher lows / tightening structure" has no dedicated feature anywhere.**
  `pre3_range_contraction` (range[t]/range[t-2]) is the closest proxy, but it is not a
  higher-lows sequence specifically. See **H02**.
- **NBSS/flow buildup exists only as a same-window ratio, never a multi-day persistence
  or acceleration feature.** `pre{w}_nbss_to_value` and `PRE_FLOW_BUILD_SIDEWAYS` exist,
  but nothing tests "N consecutive days of rising NBSS dominance" as its own signal. See
  **H04**.
- **ARA (price-limit) boundary distance is explicitly blocked, project-wide, not merely
  unused** (`telegram-family-feature-availability-v1.json`:
  `ARA_BOUNDARY_REFERENCE`/exchange-status flags are
  `"NOT_YET_BOUND_AS_GOVERNED_CAUSAL_ARRAY"`). Worth a narrow, clearly-labeled
  research-only proxy attempt — see **H11** — but this is capability-gated, not just an
  oversight.
- **Participant/broker gross buy-vs-sell flow** (as opposed to the current net NBSS
  proxy) is explicitly flagged in the Behavior Handbook (§31) as an unproven, unresearched
  future capability requiring a dedicated HPX/QHPX feed-capability investigation before
  any code can use it — correctly left alone by all current code; noted here only so
  it isn't silently forgotten as "already covered" by NBSS.
- **Time-of-day interaction with multi-day precursors is computed but not tested.** V8
  buckets `TIME_09/10_11/12_13/14_PLUS` as one marker among many, but no version tests
  whether a given multi-day precursor's hit rate actually *depends* on which time band
  ignition occurs in. See **H08**.
- **The raw schema's ~70 columns include IDX session/clock-window and data-quality flags
  (gap detection, duplicate/out-of-order, OHLC-validity, negative-volume) that are used
  for eligibility filtering but never as causal features in their own right** (e.g. a
  ticker-day with a recent data-quality flag might behave differently post-flag — never
  tested).

---

## 4. Winner precursor archetypes across the governed corpus — **PARTIAL, not yet a full data-backed map**

What can be said from *existing* evidence alone (no new bars pulled yet): the only
archetype with quantified support is the V4 bridge sequence — **parent
`K06_EARLY_RETAINED_FLOW` (itself `J05_FLOW_RESILIENT_CONTINUATION` AND
`J06_EARLY_STRENGTH_RETAINED`) → held flow across publications → a reclaim relative to
the prior 3 publications → a renewed (or fresh) high** — which repeats with a positive
median outcome across all three discovery/validation months (§2.3). No other
archetype in the corpus currently has a comparable *quantified*, cross-period-repeating
profile; V6/V7/V8's "winner families" (FAST_CLEAN, STRONG_RUNNER, RETAINED_WINNER,
HAKA_* variants) exist as code and label definitions but this audit did not find their
actual per-family hit-rate/support numbers recorded anywhere in the repo (they would
only exist in the GitHub Actions artifacts, which are `UNAVAILABLE` from this sandbox —
see "Session blockers"). **Building a genuine data-backed archetype map requires
pulling representative winner events from the governed shards and is queued as the
first real experiment once execution access exists.**

## 5. Matched near-twin failure archetypes — **PARTIAL, not yet a full map**

Same constraint as §4. The one concrete, quantified near-twin *population* that already
exists is the V4 bridge candidate's own Jan/Feb losing tail (Q25 −0.59% / −0.74% against
the same signature that produces +0.68%/+0.46% medians) — i.e., roughly a quarter to a
third of events matching the exact same causal signature lose money, and nothing in the
repo has yet characterized what distinguishes them. V6 has *code* for winner/near-twin
contrast (`_first_family_rep` vs `_failed_rep`) but, again, its actual output numbers
live only in artifacts this sandbox cannot reach. **This is the highest-value, most
concretely-scoped first experiment for Claude's lane — see H05.**

## 6. Independent experiment matrix (proposed — see `HYPOTHESIS_REGISTRY.json`)

Rather than re-running V3–V8d's own hypotheses, the following are scoped specifically at
the underused dimensions identified in §3, plus the one concrete open problem in §4/§5.
Full machine-readable form, including exact feature definitions and data dependencies,
is in `HYPOTHESIS_REGISTRY.json`. Summary:

| ID | Hypothesis | Type |
|---|---|---|
| H01 | Repeated close-location/acceptance count over rolling N bars as precursor | multi-day |
| H02 | Progressive higher-lows / tightening-structure sequence | multi-day |
| H03 | Matrix-profile (STUMPY) "quiet period → wake" motif detection, wiring the disconnected Lane-2 pattern-discovery engine into MG | multi-day |
| H04 | Multi-day NBSS persistence/acceleration (consecutive-day buildup, not just a single-window ratio) | multi-day |
| H05 | **Near-twin failure discriminator for the frozen V4 bridge signature's Jan/Feb losing tail** | anti-failure / discriminator |
| H06 | Volume-led ignition as an independent family from value/NBSS-led ignition | intraday |
| H07 | Repeated-test-of-level behavior (multiple bounces off the same support/resistance) | multi-day |
| H08 | Time-of-day interaction with multi-day precursor reliability | interaction |
| H09 | Research-only intrabar VWAP proxy reconstructed from 1-minute bars, to finally test VWAP-acceptance hypotheses (clearly labeled as a proxy, never "true" VWAP) | intraday |
| H10 | Systematic re-audit of all lookback-based features for the same session-boundary-contamination bug found in `telegram_mg_precision_study.py` | data-quality audit |
| H11 | Narrow, clearly-labeled research-only ARA-boundary-distance proxy (capability-gated; may resolve to UNAVAILABLE) | multi-day, capability-gated |

Each will be run discovery-only on Dec 2024, thresholds frozen, then replayed unchanged
on Jan+Feb 2025, per the project's non-negotiable rules. March 2025 stays untouched OOS.
None of these have been executed yet — this audit is Phase 0 (reading), not Phase 1
(experiments).

## 7. Validation results by period — **PENDING.** No new experiment has been run yet.

## 8. Surviving formula families — **PENDING.** None proposed by Claude's lane yet;
`MG_RR_FLOW_RENEW_V4`/`MG_RR_FLOW_FRESH_V4` are GPT-lane frozen research candidates
(not canonical, not independently re-validated by Claude).

## 9. Coverage / missed-winner analysis — **PENDING.**

## 10. Comparison plan against GPT lane

Once H01–H11 (or whichever survive early screening) produce discovery-stage candidates,
Claude's lane will report, per CLAUDE.md's collaboration rule: Claude-only surviving
candidates; overlap with GPT's V4–V8d frozen/candidate signatures (mechanically checkable
since both read the same governed corpus); union-of-families coverage vs. either lane
alone; and which lane's apparent edges fail out-of-sample first. Because F01–F06 is a
same-day, not-yet-MG-mapped initiative (see §0), it is tracked as a third reference point
but not treated as MG-equivalent unless the owner says otherwise.

---

## Session blockers encountered during this audit (read-only phase)

1. **GitHub push access**: this Cowork session cannot push to
   `DontAsk3010/a1-clean-orchestration` — the git proxy reports the repo is "not in this
   session's authorized repository set." This document, the ledger entry, and the
   hypothesis registry are committed **locally only** in this session's working tree and
   will be pushed as soon as access is granted.
2. **GitHub REST API (Actions runs/jobs/artifacts)**: every `api.github.com` call from
   this sandbox — including to an unrelated public repo used as a control — returned an
   identical `403` body: `"GitHub access to this repository is not enabled for this
   session. Use add_repo to request access..."`. This is a sandbox-level gate on the API
   path specifically (plain `git clone`/`ls-remote` is unaffected), separate from the
   push-authorization issue above. Practical effect: the specific run IDs CLAUDE.md asks
   to inspect (`35006408023`, `34999944377`, `35013142224`, `35030436199`) and the
   broader MG-related workflow-run history could not be read this session. Recorded as
   `UNAVAILABLE`, not inferred.
3. **Governed raw/behavior data plane (Google Drive)**: accessible and characterized
   (18 monthly RAW CSVs, Dec 2024–May 2026, ~10–11GB total; a sharded/manifested
   `UNIVERSAL_BEHAVIOR_DATA_PLANE_CURRENT` structure keyed by month, not by
   ticker/date). Small manifests/indexes were read; bulk raw/shard/bundle data was
   deliberately not downloaded in this read-only phase. A targeted pull strategy
   (resolve month → manifest → specific shard, not a bulk fetch) is feasible for the
   experiments in §6 once this lane moves to execution.

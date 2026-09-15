# CLAUDE CODE ENTRYPOINT — A1 CLEAN / QHPX — MG INDEPENDENT RESEARCH LANE

This branch is the independent Claude Code research lane for **Telegram A / EARLY_POTENTIAL / 👀 MULAI GENIT (MG)**.

## Core instruction

Do not begin by inventing a formula or by polishing GPT's latest formula. First read the repository, prior research code, requests, workflow history, logs, artifacts, and existing results. The goal is to independently discover causal market-behavior formulas from the richest available governed historical data, then validate them without hindsight.

The user's required working style is **practice first**: inspect and process the data, run tests/replays, record empirical findings, and only then explain conclusions. Do not replace execution with theory.

## Non-negotiable project rules

1. Full-universe: include all eligible IDX ticker-days available in governed sources; never cherry-pick winners only.
2. Causal runtime state only. Future bars/outcomes may be used only as research labels/teacher variables, never as formula inputs.
3. Missing/unproven data is UNKNOWN/UNAVAILABLE, never silently zero.
4. Preserve exact chronology and source-supported timestamps. Do not backdate a signal after seeing the outcome.
5. Formula research may use multiple independent families. Do not force all winner behavior into one formula.
6. Do not rescue a structurally weak formula by repeatedly loosening thresholds.
7. A formula must be validated on different periods without retuning. March 2025 is untouched OOS unless the authority explicitly changes.
8. Do not modify or delete GPT research files as part of Claude discovery. Add Claude-owned files with `claude_` naming or under `research/claude-mg-discovery/`.
9. No live/canonical promotion. Everything in this lane remains RESEARCH_ONLY until separately governed and authorized.
10. Do not claim that bars identify a specific 'bandar'. Use measurable terms: positioning, accumulation-like behavior, absorption, volume/value expansion, flow, price acceptance, ignition, crowd/demand expansion, failure/distribution-like behavior.

## What to read BEFORE changing code

Read these repo-native materials completely:

- `README.md`
- `docs/architecture.md`
- `docs/parity-contract.md`
- `docs/recovery-contract.md`
- `src/a1clean/formula_research/formula_replay.py`
- `src/a1clean/formula_research/telegram_mg_replay.py`
- `src/a1clean/formula_research/telegram_mg_multiday_context_study.py`
- `src/a1clean/formula_research/telegram_mg_behavior_topology_v2.py`
- `src/a1clean/formula_research/telegram_mg_sequence_discovery_v4.py`
- `src/a1clean/formula_research/telegram_mg_outcome_first_discovery_v5.py`
- `src/a1clean/formula_research/telegram_mg_trajectory_contrast_v6.py`
- `src/a1clean/formula_research/telegram_mg_high_conviction_v7.py`
- `src/a1clean/formula_research/telegram_mg_multihypothesis_v8.py`
- `src/a1clean/formula_research/telegram_mg_multihypothesis_v8b.py`
- `src/a1clean/formula_research/telegram_mg_multihypothesis_v8c.py`
- `src/a1clean/formula_research/outcome_path_quality.py`
- `formula-packs/`
- `formula-research/`
- `plans/`
- all MG request directories (`mg-*`, `telegram-mg-*`) and relevant `.github/workflows/` files.

Then inspect the **git history** for those paths. Earlier failed approaches are evidence; do not erase them mentally.

## Actions / artifact history that must be reviewed

Inspect GitHub Actions runs, job logs, and downloadable artifacts for MG research. At minimum review these known run IDs where available:

- `35006408023` — corrected V4 first-trigger replay authority.
- `34999944377` — V5 full-universe outcome-first discovery.
- `35013142224` — December 5-minute Telegram snapshot replay.
- `35030436199` — V8D multi-hypothesis full-corpus run/current lineage; inspect its final status/log/artifact rather than assuming success.

Also enumerate other workflows/runs whose names contain `MG`, `Telegram MG`, `trajectory`, `high-conviction`, `multihypothesis`, `frozen candidate`, or `formula research`. Read the artifact JSONs, not only workflow summaries.

If an artifact or connected Drive source is inaccessible, record it explicitly as `UNAVAILABLE` and continue with what is verifiably accessible. Do not infer missing results.

## Data semantics to preserve

Current governed RAW mapping used by the research code includes:

- OHLC
- Volume
- `RAW_Aux2` / physical Aux2 = `TRADE_VALUE_1M`
- `RAW_OpenInterest` / physical OpenInterest = `NBSS_VALUE_1M` in this dataset context; it is not futures open interest.
- Derived HAKA/HAKI-like flow estimates, where used, are estimates from value/NBSS semantics and are not true L1 bid/ask/order-book observations.

Research execution proxies are historical approximations. Never describe them as proven exact HAKA fills unless true L1 ask/queue data is present.

## Actual MG live/publication intent

The eventual production architecture is:

`HPX/AmiBroker universal IDX scan -> canonical current market state -> multiple fixed formula families -> Telegram presentation`.

AmiBroker/universal engine scans the whole eligible universe once. Formula families do not perform independent market scans; they consume the same current state.

MG publication contract:

- starts 09:00 WIB;
- every valid 5-minute publication slot;
- public live columns remain `CODE | PRICE | CHG% | TP-1 | TP-2`;
- TP-1/TP-2 are dynamic per snapshot;
- if a ticker still satisfies the applicable MG criteria at the next 5-minute snapshot, it MUST appear again; repeated appearances are expected, not duplicates;
- if it ceases to qualify, it disappears; it may reappear if it qualifies again later;
- replay-only reports may add TP hit time / P&L / path-quality columns, but those are outcome analysis, not the live signal contract.

## Main research question

Use the full governed data to discover **multiple causal precursor -> ignition families**, not one guessed formula.

The user explicitly wants systematic testing of many hypotheses including, but not limited to:

### Multi-day precursor hypotheses

- sideways/base for 2/3/5/8/10 days before expansion;
- volatility/range compression before expansion;
- rise -> deep pullback -> multi-day base -> renewed move;
- decline/shakeout -> stabilization -> base -> ignition;
- abnormal volume while price remains contained;
- abnormal trade value while price makes little progress;
- high effort / low price progress as possible absorption-like positioning;
- NBSS/flow build-up or change while price remains relatively contained;
- repeated close-location/acceptance behavior inside a range;
- progressive higher lows or tightening structure;
- prior high/reclaim proximity;
- quiet period followed by activity wake;
- any other recurring precursor the data reveals. Do not limit discovery to this list.

### Intraday ignition hypotheses

At every valid 5-minute snapshot test causal features such as:

- relative Volume wake and acceleration;
- relative Trade Value wake and acceleration;
- range expansion;
- price-path acceleration;
- price acceptance near high;
- fresh high / reclaim / renewed high;
- flow expansion/continuation when availability is proven;
- response efficiency: price progress relative to effort/value;
- pullback/reclaim/reacceleration;
- early-session vs late-lift distinction;
- failure markers: large activity without price progress, rejection, stale high, distribution-like response, late chase, one-bar spike, etc.

## Critical methodology

Do **not** choose arbitrary thresholds such as `volume > 2x` because they sound plausible. Generate continuous features, learn candidate cut points/quantiles only from the discovery block, freeze them, and replay the unchanged formula on validation blocks.

Do not collapse rich continuous data into a tiny set of booleans too early. Preserve and analyze continuous ratios/distributions first; booleans/signatures may be created only after the empirical separation is understood.

Compare each strong winner path with **near-twin failures**: cases that looked similar before/at ignition but failed afterward. The useful formula is the causal difference visible before the outcome, not the description of the winner after the fact.

## Required experimental breadth

Run many independent hypotheses and combinations in parallel. A candidate family should normally contain at least:

- one multi-day precursor condition;
- one current-day/intraday ignition condition;
- optional anti-failure condition(s).

Do not repeatedly mutate one formula until it fits. Keep a registry of hypotheses including failures, support, precision, coverage/recall, and validation performance.

## Outcome / validation measurements

For each candidate and for the union/intersection of useful families report at minimum:

- signal/event count;
- unique ticker-days and unique dates;
- positive net MFE rate;
- Q10 / Q25 / median / Q75 / Q90 net MFE;
- MAE and pre-peak MAE;
- time/number of bars to first positive net outcome;
- time to peak;
- reward-to-adverse ratio;
- TP-1 hit rate and first hit time when replay target exists;
- TP-2 hit rate and first hit time when replay target exists;
- same-day EOD retention where relevant;
- profitable opportunity coverage / recall;
- missed winners;
- false positives;
- comparison with unconditional/full-universe baseline;
- discovery vs each untouched validation period separately.

A candidate that only produces ~55% positive rate with negative Q25 is not considered a high-quality MG answer merely because it beats a ~50% baseline slightly.

## Independent Claude lane output

Do not simply copy or tweak the GPT result. Create an independent research trail.

Write outputs under:

- `research/claude-mg-discovery/RESEARCH_LEDGER.md` — append-only chronological experiments, including failures.
- `research/claude-mg-discovery/HYPOTHESIS_REGISTRY.json` — machine-readable hypothesis registry.
- `research/claude-mg-discovery/results/` — result JSONs/summaries.
- `src/a1clean/formula_research/claude_*.py` — Claude-owned research code if code is required.
- `.github/workflows/claude-*` — Claude-owned workflows if execution is required.

Every result must record source identity, commit SHA, workflow/run ID when applicable, formula/signature, discovery period, validation period, support, metrics, and whether future data was used only as a label.

## First deliverable

Before proposing a final formula, produce `research/claude-mg-discovery/RESEARCH_AUDIT.md` containing:

1. What prior GPT/repo research actually tested.
2. Which approaches failed and why, based on artifacts/results rather than opinion.
3. What rich data dimensions were underused.
4. A data-backed map of winner precursor archetypes found across the corpus.
5. A matched map of near-twin failures.
6. The set of independent experiments Claude will run.
7. Results of those experiments and surviving candidates.

Only after this audit and validation should Claude propose a candidate formula pack.

## Collaboration rule with GPT lane

Treat GPT and Claude as independent researchers using the same governed evidence. Do not optimize toward agreement. Later, compare:

- Claude-only candidates;
- GPT-only candidates;
- union of families;
- intersection / consensus conditions;
- which system captures profitable opportunities the other misses;
- which apparent edges fail out of sample.

The data decides. Agreement between models is not itself validation.

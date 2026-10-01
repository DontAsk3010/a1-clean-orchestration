# Machine 2 CURRENT Semantic Reader Contract — 2026-10-01

STATUS: PILOT-VALIDATED READING CONTRACT / FULL HEAVY RUN STILL HOLD UNTIL SUCCESSOR INTEGRATION

This file operationalizes the CURRENT Master/Behavior reading rules for Machine 2 without changing Master authority.

## Input unit
- Default semantic unit is ONE COMPLETE TICKER-DAY reconstructed from the lossless semantic bundle.
- If the governed source resolution is 1 minute (`RAW_INTERVAL_SEC=60`), EACH ACTUAL SOURCE ROW is one 1-minute observation and MUST be read in exact source chronology.
- Read from actual FIRST_OBSERVED_TIME through actual LAST_OBSERVED_TIME for that ticker-day.
- No row-count shortcut, mover/winner filter, interesting-only filter, or selected-time filter.

## Missing-minute rule — HARD
- A missing 1-minute source row is NOT a flat bar, NOT zero, NOT a synthetic observation, and NOT evidence that price was unchanged.
- When two source rows are separated by a gap, preserve the gap as NO_SOURCE_OBSERVATION / source gap state according to proven source semantics.
- The first later observed state is only the FIRST PROVEN/OBSERVED state after the gap; do not backfill an event time into an unobserved minute.

## Sparse ticker rule — HARD
- Sparse/illiquid/no-event ticker-days remain first-class evidence.
- Read every actual row even when there are only 1, 3, 6, or another small number of rows.
- Do not invent continuity between sparse observations.
- A sparse day may remain OBSERVED / UNNAMED / AMBIGUOUS / OPEN when evidence is insufficient for a stronger interpretation.

## Semantic authority separation
- Python/Colab may preserve, index, verify, partition, account, and derive only source-linked deterministic facts.
- Python/Colab MUST NOT invent behavior/event/journey meaning, rule-based semantic labels, thresholds, scores, BUY/SELL logic, formula proxies, precursor boundaries, or event boundaries.
- The language-model semantic reader performs behavior interpretation from the complete lossless chronological evidence.

## Evidence discipline
For every actual available row and material transition, preserve where supported:
- exact source-linked timestamp/time range;
- source row/range identity;
- OHLC path, high/low lifecycle, volume/activity/value when semantics are proven;
- session/mechanism flags and gap/data-quality state;
- effort versus response / non-response only from proven evidence;
- repeated tests/attempts, persistence, retention/giveback, acceleration/deceleration, failure/recovery, loops/revisits, maturity/decay when actually supported;
- negative evidence and expected-but-absent confirmation;
- formation/causal-known-at state separately from hindsight resolution;
- OPEN/LEFT_CENSORED/RIGHT_CENSORED/UNKNOWN/UNAVAILABLE states;
- near-twin/lookalike links and contextual evidence when proven.

## Availability / semantics gate
- Never assign meaning to RAW_OPENINT_PHYSICAL, RAW_AUX1_PHYSICAL, RAW_AUX2_PHYSICAL or another physical vendor slot unless CURRENT source semantics prove that mapping for the exact source/version/scope.
- Missing or unproven lanes remain UNKNOWN / UNAVAILABLE / UNPROVEN / NOT_APPLICABLE / STALE / PARTIAL as appropriate.
- Missing is never zero.
- Do not infer broker/participant/aggressor/order-book/hidden-liquidity/bandar intent from OHLCV alone.

## Output discipline
Each pilot/full semantic object must separate:
1. SOURCE FACTS / primitive observed chronology.
2. DETERMINISTIC DERIVED FACTS, if used, with reproducible provenance.
3. DESCRIPTIVE SEMANTIC INTERPRETATION grounded in exact source evidence.
4. CAUSAL / FIRST-DETECTABLE / KNOWN-AT state.
5. HINDSIGHT-COMPLETE later resolution, separately.
6. UNCERTAINTY / CONTRADICTION / UNKNOWN / OPEN state.

Do not compress a multi-state path into one terminal label. Labels are views over evidence, never replacements for evidence.

## Formula wall
FORMULA/MODEL/SCORE/THRESHOLD/RANKING/SELECTOR/BUY-SELL/TP-SL stage remains CLOSED.

## Promotion gate
A successor Machine 2 semantic engine may leave HOLD only when a representative pilot proves:
- complete actual 1M/source-row reading;
- sparse/missing handling above;
- ticker-specific non-template interpretation;
- exact time/source linkage;
- no Python semantic substitution;
- no unproven field semantics;
- causal/hindsight separation;
- durable pilot readback.

V2 rule-based semantic outputs remain NON-CURRENT scientific completion and may not seed the successor semantic interpretation.

# Machine 2 CURRENT Full-Depth Reading Contract — 2026-10-01

STATUS: OWNER-HARD-LOCK ALIGNED / FULL HEAVY RUN HOLD UNTIL FULL-DEPTH COVERAGE + PRESTART PROOF

This file operationalizes the latest OWNER HARD LOCK together with the CURRENT Master. It does not reduce either authority.

## Authority precedence
OWNER LATEST EXPLICIT DIRECTIVE -> CURRENT MASTER -> CURRENT EXECUTION -> applicable CURRENT handbooks/locks -> request -> code/tests -> runner/run/output.
Implementation must be corrected to authority; authority must never be reduced to fit implementation.

## Machine 2 role
Machine 2 is an INDEPENDENT FULL-DEPTH RESEARCH ENGINE. Deterministic/programmatic/algorithmic automation, Python, GitHub Actions, runner workflows, schemas, derived calculations, corpus-scale processing and automated detection are ALLOWED.

Different method is allowed. Different scientific depth is NOT allowed.
Target: METHOD-INDEPENDENT MAXIMUM SOURCE-SUPPORTED COMPLETENESS.

## Actual source chronology — HARD
- Default scientific unit is ONE COMPLETE TICKER-DAY reconstructed from governed lossless evidence, with cross-date carry preserved.
- If governed source resolution is 1 minute (`RAW_INTERVAL_SEC=60`), EACH ACTUAL AVAILABLE SOURCE ROW is one 1-minute observation and MUST be processed in exact source chronology.
- Read/process all actual rows from actual FIRST_OBSERVED_TIME through actual LAST_OBSERVED_TIME.
- No sampling, selected-minute, winner/mover-only, ARA-only, candidate-only, summary-only, first/last-only, high-low-only, 5-minute substitution, or daily-summary substitution.
- Missing 1-minute rows are NOT flat bars, NOT zero, and NOT synthetic observations. Preserve source gaps explicitly. The next observed state is the FIRST PROVEN/OBSERVED state after the gap; do not backdate an unseen transition into the gap.
- Sparse/illiquid/no-event ticker-days remain first-class evidence. Read every actual row even when only 1, 3, 6, or another small number exist.

## Primitive facts — preserve before compression
Preserve all source-supported physical lanes and provenance, including where available:
DATE/TIME, OPEN, HIGH, LOW, CLOSE, VOLUME, VALUE, ACTIVITY/FREQUENCY, NBSS/FLOW, HAKA/HAKI, reference fields, status/mechanism, source row identity, source/header/version/digest and all other physical governed fields.
Unknown semantics remain UNKNOWN/UNPROVEN; physical presence alone does not prove analytical meaning.

## Required Machine 2 research domains
Every applicable domain below is mandatory when source-supported. If unavailable, persist the explicit availability state and reason instead of dropping the domain.

1. EXACT TIME / CAUSALITY
   - EVENT_TIME, SOURCE_TIME, RECEIVE_TIME if available, INGEST_TIME if available, PROCESS_TIME when relevant, KNOWN_AT_TIME, FORMATION_ELIGIBLE_AT_TIME, HINDSIGHT_RESOLUTION_TIME.
   - No backdating. Later outcomes never become hidden formation inputs.

2. PRICE PATH / LOCATION / MEMORY
   - body, wick, range, displacement, cumulative/path length, path efficiency, gap/open relation, running high/low, fresh extremes, prior high/low/open/close relation, distance travelled, base/congestion and price-location context.
   - Continuous evidence remains available even when categorical views are created.

3. EFFORT VS RESPONSE
   - preserve effort definition, response/displacement definition, window, direction, lag, persistence, known-at and availability.
   - support large/small effort vs large/weak/no/opposite/delayed/reversal response when evidence supports it.
   - absorption is only an evidence-backed interpretation, never a default label.

4. NEGATIVE / QUIET / FAILURE / CONTRADICTION
   - effort without progress; activity without displacement; breakout without follow-through; reclaim without continuation; fresh extreme without confirmation; expected confirmation absent; divergence; contradiction; failure; trap-like path; quiet/no-event counterpart.

5. ATTEMPTS / RETESTS / LOOPS
   - attempt number/start/end, interval between attempts, effort/response/range change, test/retest, attack/defense, reclaim/hold/rejection/acceptance/fail/retry/reacceleration, state revisit, loop count and nested episodes.

6. MATURITY / PERSISTENCE / DECAY
   - state start, age, duration, persistence, acceleration/deceleration, maturity, weakening, decay, exhaustion, disappearance, reappearance and diminishing response.

7. LEAD-LAG
   - supported lane relationships including price/flow, flow/price, volume/range, range/volume, value/price, HAKA-HAKI/price, price/HAKA-HAKI, liquidity/response and other proven lanes.
   - preserve which lane moved first, lag, direction, persistence and recurrence.

8. EVENT / JOURNEY / LIFECYCLE
   - precursor, initiation, development, transition, extreme, continuation, weakening, failure, recovery, rebase, transformation and resolution.
   - journeys do not terminate merely because a chunk/file/date/workflow step ends.

9. CROSS-DATE CONTINUITY / OPEN / CENSORING
   - prior-day state, overnight carry, next-day continuation, transformation, recovery, failure, OPEN journey, RIGHT_CENSORED, LEFT_CENSORED and observation-end reason.

10. CONTEXT
   - market, sector, cross-sectional, ticker personality, liquidity regime, session/mechanism, auction, FCA, price limit, suspension/reopen, corporate action, structural break and provider/data regime where source-supported.

11. DATA QUALITY
   - gap, duplicate, out-of-order, stale, delayed, partial, reconnect, correction, clock mismatch, schema drift, lane disappearance and feed issue are tracked separately from market behavior.

12. NEAR-TWIN / COUNTEREXAMPLE
   - material formations must support comparison to similar formations with different later resolutions using only pre-divergence information. If no causal discriminator exists: AMBIGUOUS / UNCONFIRMED / ABSTAIN is valid.

13. BASE RATE / DENOMINATOR READINESS
   - retain enough corpus information to calculate occurrence and resolution denominators by ticker/date/month/liquidity/session/regime/context and outcome-without-formation.

14. FORMATION SNAPSHOT
   - reconstruct exact causal time T: source identity/version, available rows, primitive facts, deterministic derived facts, semantic states, availability, context, journey position, timing/lag/persistence/maturity and definition versions. Later outcome stored separately.

15. HINDSIGHT WALL
   - FORMATION / KNOWN_AT and HINDSIGHT RESOLUTION are physically and logically separate. Hindsight may store later resolution metrics but cannot rewrite earlier formation state.

16. AVAILABILITY / UNKNOWN
   - use AVAILABLE, TRUE_ZERO, UNKNOWN, UNAVAILABLE, NOT_POPULATED, NOT_ENTITLED, UNSUPPORTED, STALE, DELAYED, PARTIAL, NOT_APPLICABLE, UNPROVEN, PREPARED_FUTURE_LANE as supported. Zero is never a substitute for unknown.

17. DYNAMIC SOURCE UNIVERSE / PROVENANCE
   - discover eligible sources dynamically and reconcile discovered, valid processed, atlas-consumed and reconciled source sets. Fixed historical source counts are not completion authority.

## Programmatic semantic/state detection — ALLOWED WITH FULL LINEAGE
Machine 2 MAY calculate, scan, derive, compare, link, group, count, detect transitions, calculate lag/response, build journeys, find near-twins, maintain denominators, reconcile, persist and read back programmatically.

A programmatic state/label such as ACCUMULATION, BREAKOUT, RECLAIM, FAILURE, RECOVERY, ABSORPTION_EVIDENCE or EXHAUSTION is not forbidden merely because Python produced it. But it is INVALID as full-depth evidence unless it carries:
- definition_version;
- source parents and exact row/time range;
- known-at eligibility;
- deterministic derived parents;
- explicit reason/features;
- availability state;
- uncertainty/contradiction state;
- transition lineage;
- and enough underlying continuous evidence to audit the path.

Labels are views over evidence, never replacements for evidence.

## Current implementation treatment
Existing valid canonical RAW/source identity, lossless packets/bundles, dynamic discovery, integrity/provenance, chronology, deterministic continuous descendants, state runs, lifecycle timing, path objects, formation snapshots and valid checkpoints MAY be reused after CURRENT compatibility proof.

Existing derived/semantic layers are NOT rejected merely because they are programmatic. They must be classified per domain as IMPLEMENTED_AND_PROVEN, IMPLEMENTED_NEEDS_REVALIDATION, SEMANTIC_REPRESENTATION_GAP, DATA_COVERAGE_GAP, PROVEN_UNAVAILABLE, NOT_APPLICABLE_WITH_REASON, FUTURE_LANE_NOT_ADMITTED, or HOLD.

Affected missing/invalid dimensions must be enriched/recomputed. Do not preserve wrong work merely to avoid rework; do not blind-rebuild valid unaffected substrate.

## PASS discipline
SOURCE_ACCESS_PASS, RAW_INTEGRITY_PASS, TRANSPORT_PASS, DETERMINISTIC_DERIVATION_PASS, SEMANTIC_REPRESENTATION_PASS, JOURNEY_PASS, GROUPING_PASS, ATLAS_PASS, MASTER_COVERAGE_PASS and CURRENT_HORIZON_COMPLETE are separate claims.
Workflow green or run completed is not scientific completion.

## Formula wall
FORMULA / MODEL / SCORE / THRESHOLD / RANKING / SELECTOR / BUY-SELL / TP-SL stage remains CLOSED.

## Heavy-run promotion gate
Heavy Machine 2 restart may leave HOLD only after CURRENT authority sync + coverage matrix + request + exact HEAD + tests + PRESTART prove that every implementable hard-lock domain is represented or explicitly held/unavailable without silent omission.

The prior `HOLD_METHOD_NONCOMPLIANT_PYTHON_SEMANTIC_SUBSTITUTION` interpretation is SUPERSEDED by this OWNER-HARD-LOCK-aligned contract. Programmatic processing is permitted; shallow or unauditable processing is not.

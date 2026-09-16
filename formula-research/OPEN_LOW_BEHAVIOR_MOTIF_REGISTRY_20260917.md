# A1 CLEAN / QHPX — OPEN LOW BEHAVIOR MOTIF REGISTRY

Status: RESEARCH_ONLY_NOT_CANONICAL
Date: 2026-09-17 WIB
Authority: ACTIVE MASTER + CURRENT EXECUTION + FORMULA RESEARCH HANDBOOK V2
Naming lock: current experimental Open=Low line is **OPEN LOW**, not MULAI GENIT/MG.
Reserved OOS remains untouched until governed promotion gates permit it.

## Owner-locked research correction

The project already has more than one year of governed IDX 1-minute behavior data. The research task is not to wait for the owner to feed individual pattern ideas. The worker must proactively mine recurring behavior sequences, compare winners with near-twin failures, translate recurring behavior into causal states, then encode candidate state-machines.

Classical indicators are optional. The required representation layer is observable market behavior:

`prior condition -> initiation -> initial push -> pullback -> defend/break -> reclaim -> reacceleration -> continuation/failure`

Future bars may evaluate a past state but may never participate in the live trigger.

## OPEN LOW decomposition

### Phase A — H-1 precursor/setup
Questions to mine without assuming the next-day gap is known:
- Was H-1 quiet, compressed, or sideways?
- Did transaction value/volume/valid flow build while price progress stayed contained?
- Was there a late-day reclaim, close-location improvement, higher-low structure, or failed sell pressure?
- Did H-1 end with a state that historically precedes next-day gap/open-strength more often than near-twin controls?

### Phase B — H0 opening state
- Gap/open versus H-1 close.
- OPEN equals/anchors the running low versus OPEN being broken.
- Initial push size, speed, and retention.
- Early price progress relative to value/volume effort.
- High progression freshness and persistence.

### Phase C — H0 continuation/failure
- Pullback begins after the initial push.
- OPEN/near-OPEN defended versus broken.
- Reclaim of pre-pullback level.
- Fresh/renewed high after reclaim.
- Reacceleration versus weak/no follow-through.
- Giveback/failure state.

## Initial motif registry

| ID | Behavioral sequence to test | Positive continuation hypothesis | Near-twin failure control | Status |
|---|---|---|---|---|
| OL01 | OPEN LOW -> initial push -> pullback -> OPEN/near-OPEN defended -> reclaim -> fresh high | defended pullback behaves as reload before continuation | same initial push, but OPEN defense fails or reclaim fails | READY_TO_MEASURE |
| OL02 | OPEN LOW -> early push -> shallow pause -> second acceleration before deep pullback | two-wave continuation identifies stronger early demand | one-wave spike then full giveback/no second wave | READY_TO_MEASURE |
| OL03 | OPEN LOW -> effort expands while price progress temporarily stalls -> price response resumes | temporary absorption/stall can precede efficient reacceleration | effort stays high but price remains inefficient/rejects | READY_TO_MEASURE |
| OL04 | OPEN LOW -> pullback low remains above OPEN -> higher-low -> reclaim | higher-low above OPEN distinguishes healthy retrace | same pullback depth range but new low breaks OPEN | READY_TO_MEASURE |
| OL05 | OPEN LOW -> high made early -> pullback -> cannot reclaim prior high -> stale state | identifies trap/late chase rather than continuation | matched state that reclaims and renews high | READY_TO_BUILD_FAILURE_CONTROL |
| OL06 | H-1 contained effort/value build -> H0 gap/open strength -> OPEN LOW persistence | H-1 precursor may improve selection before/at open | similar H-1 build but H0 fails to defend OPEN | READY_TO_MEASURE |
| OL07 | H-1 decline/shakeout -> recovery close -> H0 OPEN LOW -> reclaim/continuation | recovery precursor may produce next-day continuation | similar H-1 recovery but H0 immediate failure | READY_TO_MEASURE |
| OL08 | OPEN LOW -> price rises immediately with little adverse excursion -> persistent fresh highs | clean directional continuation family | immediate rise that stalls and later reverses deeply | READY_TO_MEASURE |
| OL09 | OPEN LOW -> initial push -> material pullback -> OPEN defended -> delayed recovery later in session | deep-but-defended retrace can still be valid if response reappears | deep retrace where response never returns | READY_TO_MEASURE |
| OL10 | OPEN LOW -> small initial profit -> high stagnates -> downside excursion expands | early tiny profit may hide a failure path | same early profit but renewed high progression follows | READY_TO_BUILD_FAILURE_CONTROL |

## Mandatory measurements per motif

- support count and unique ticker-days;
- event start, first-detectable time, signal time, end/resolution time;
- H-1 context and H0 gap/open context;
- OPEN defended/broken state;
- signal -> post-entry low time;
- signal -> post-entry high time;
- low-first versus high-first ordering;
- MFE / MAE;
- max rise / max drawdown;
- net max opportunity after fees;
- reclaim timing and fresh-high timing when relevant;
- winner versus matched near-twin failure divergence;
- discovery / Validation A / Validation B consistency;
- hindsight/causality audit.

Thresholds must be derived from empirical distributions/contrasts in governed discovery data and frozen before validation. Do not invent a cutoff to rescue a weak candidate.

## Locked human-readable OPEN LOW report V2

Keep the same default columns/order across future OPEN LOW AFL/replay variants unless the owner explicitly changes it:

`SAHAM | WAKTU SIGNAL / BUY | OPEN HARI | HARGA ENTRY | CHG% SIGNAL | LOT | MODAL | MIN LOW SETELAH ENTRY | WAKTU MIN LOW | MAX TURUN % | MAX LOSS BERSIH | MAX HIGH SETELAH ENTRY | WAKTU MAX HIGH | MAX NAIK % | MAX PROFIT BERSIH | URUTAN GERAK | HASIL`

`HASIL=PROFIT` means the historical post-entry path offered positive net opportunity after fees. `HASIL=LOSS` means even the best later high did not offer positive net profit. This is not realized P/L. Realized P/L requires an explicit causal SELL rule.

## Next exact work

1. Use the durable governed non-OOS 1-minute corpus/cache.
2. Measure OL01–OL10 without outcome leakage.
3. Build matched near-twin failure sets rather than arbitrary losers.
4. Rank motifs by robustness, not by a single attractive hit-rate.
5. Preserve negative results.
6. Expand the registry with additional motifs discovered directly from the corpus; do not stop at OL01–OL10 and do not wait for user suggestions.
7. Freeze viable sequence definitions before Validation A/B and before any reserved OOS access.

END

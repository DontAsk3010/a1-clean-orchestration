# BBCA — 2024-12-03 — Working scientific source review (NOT A MASTER PASS)

Source: Raw Des 02-31-2024.csv, SHA256 5bddb43f243e3cbb76504ecc38d8b0981e38866b7a4ea3b4557dcbbf3024712c. Original source rows 157676–158011. Post-claim governed GitHub source evidence read chronologically in 9 parts (40×8 +16), 336/336 distinct source rows, no duplicate or missing source row. Evidence JSONL SHA256 3142f1a08339c6fb9057a863b440280901c8a2a7fe009f08eab451ff217db85b.

## Chronological observed path

- 08:59 single-point 10025/10025, volume 10,947,600: pre-regular price state; do not infer executable preopen trade or broker.
- 09:00 10025→9900 with high 10025 low 9900, volume 702,200; 09:01 rebounds 9900→10000 with volume 1,619,000. Rapid lower-price rejection followed by partial recovery, not proof of institutional absorption.
- 09:02–09:38 predominantly 9925–10000, repeated 9925 tests and 9950/9975 rotations. At 09:16 low 9925 and close 9975 on 1,651,600 volume; later 09:23 low/close 9925 on 1,014,800. Early selling/retest contrasts must be preserved.
- 09:39–10:18 9925–10000 range: 09:42 recovers 9950 after 9925 test with volume 1,087,400; 10:15 high/close 10000 on 1,295,000 but 10:18 low 9950 close 9950, a failed immediate upper-range persistence.
- 10:19–10:58 low 9925, high 9975: 10:51 low 9925 close 9950 volume 936,400, 10:52 low 9925 close 9975 volume 2,269,000. Again supported low tests / reversion, not proof of participant identity.
- 10:59–11:38 range 9950–10000, with 11:23 high/close 10000 volume 3,647,000, subsequent 9975–10000 retests without sustained new high.
- 11:39–13:48 range 9975–10025. At 11:43 volume 7,994,400, open/close 10000, high 10025, low 9975: major effort without net open-close displacement; later 11:44 close 10025, and 13:32 after official market break close 10025. Preserve both intrabar range and close response.
- 13:49–14:28 narrow 10000–10025 rotations; 14:20 volume 1,410,500 and open/close 10000, high 10025, low 10000: an effort–non-displacement signature, not automatic accumulation.
- 14:29–15:08 first observed 10050 high at 14:53 with volume 3,345,300; close 10025, then 14:54 close 10050 but repeated 10025/10050 rotations through 15:08. Distinguish initial failed intrabar acceptance from later upper-range persistence.
- 15:09–15:48 upper migration: 15:12 closes 10075, volume 6,034,600; 15:18 high 10100 close 10075 on 1,379,100; 15:23 low 10025 close 10075, volume 1,639,700, and 15:25 low 10025 close 10050, volume 1,083,400 (counterpressure). At 15:35 closes 10100 volume 1,655,300. 15:39 closes 10150 with volume 6,513,400; 15:42 retraces to 10100; 15:46 high 10175 close 10150 on 2,195,400. These are multiple push/pullback/retest states, not a monotonic breakout.
- 15:49 intrabar 10225 high with open 10175, low/close 10150, volume 6,011,700: rejection / non-acceptance of new extreme at bar close. Next observed row is 16:00 at 10200 flat OHLC 10200, volume 30,528,000. This is a session-phase transition and must not be fabricated as consecutive trading-minute continuation. Observed post-close through 16:14 closes 10200 without confirmed higher continuation.

## Accounted facts and constraints

Total observed volume (all 336 rows, including pre-regular and closing): 126,087,100; high 10225, low 9900. Interval coverage 08:59–16:14. There are two >1 minute observed gaps: 11:59→13:30 (official midday break, 91 min) and 15:49→16:00 (11 min, closing phase), without synthetic bars. Source packets contain RAW_AUX2 and RAW_OPENINT physical values, but fresh semantic proof flags are -1; do not classify these as broker activity, foreign flow, or HAKA/HAKI without source-scoped authoritative mapping. BAR_TIMESTAMP_SEMANTIC_CODE=-1, so bar-level causal KNOWN_AT must remain unproven. Source right censor must be evaluated separately from date-boundary OPEN lifecycle.

## State

WORKING_REVIEW_ONLY. NOT CANONICAL; NOT CHECKPOINT; NOT PASS090. Full current-Master semantic lineage, observation/journey/open descendants, cross-context audit, canonical write, exact readback and final collision gate are still required before advancing from durable PASS089.

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

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

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

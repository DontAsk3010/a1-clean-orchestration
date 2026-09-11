# a1-clean-orchestration

Governed migration of the proven A1 CLEAN/QHPX Colab data-plane to reusable Python + GitHub orchestration + a dedicated runner.

Current branch goal: **parity first**. Nothing in this repository authorizes formula, score, threshold, selector, Telegram analytical logic, or behavior-methodology changes.

## Components

- `src/a1clean/frozen_v2.py` — mechanical V2 parity anchor from the governed notebook.
- `a1clean delta` — executes the frozen engine against the configured runtime root.
- `a1clean parity BASELINE CANDIDATE` — compares governed baseline vs staging artifacts.
- `checkpoint.py` — operational restart state.
- `pattern_discovery/` — isolated Ruptures/STUMPY/DTW-tslearn wrappers with no project analytical defaults.
- `.github/workflows/ci.yml` — lightweight GitHub-hosted tests.
- `.github/workflows/parity.yml` — manual self-hosted parity only.

## Safety

For parity, `A1_RUN_ROOT` must be a **separate staging directory**. Do not point it at `UNIVERSAL_BEHAVIOR_DATA_PLANE_CURRENT`. Canonical RAW remains read-only.

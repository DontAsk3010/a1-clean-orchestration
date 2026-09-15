from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .handbook_candidates import CandidateParams as _CandidateParams
from . import telegram_mg_multihypothesis_v8b as v8b
from . import telegram_mg_multihypothesis_v8c as v8c


def _params_factory() -> _CandidateParams:
    return _CandidateParams(
        effort_lookback=5,
        progress_lookback=5,
        high_lookback=5,
        recovery_lookback=5,
        low_stabilization_bars=3,
        early_checkpoint_bar=30,
        late_lift_min_bar=120,
    )


def build_report(**kwargs: Any) -> dict[str, Any]:
    # V8B build_report constructs CandidateParams internally. Bind the same
    # governed/default research parameters used by the existing MG replay CLI.
    v8b.CandidateParams = _params_factory  # type: ignore[assignment]
    report = v8c.build_report(**kwargs)
    report["schema"] = "A1_TELEGRAM_MG_MULTI_HYPOTHESIS_V8D_RESULT_V1"
    report["candidate_params"] = {
        "effort_lookback": 5,
        "progress_lookback": 5,
        "high_lookback": 5,
        "recovery_lookback": 5,
        "low_stabilization_bars": 3,
        "early_checkpoint_bar": 30,
        "late_lift_min_bar": 120,
    }
    return report


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True)
    p.add_argument("--prior-days", type=int, default=10)
    p.add_argument("--buy-fee-pct", type=float, default=0.15)
    p.add_argument("--sell-fee-pct", type=float, default=0.25)
    p.add_argument("--min-support", type=int, default=40)
    p.add_argument("--min-unique-days", type=int, default=20)
    p.add_argument("--top-each", type=int, default=18)
    p.add_argument("--top-formulas", type=int, default=80)
    a = p.parse_args()
    report = build_report(
        prior_days=a.prior_days,
        buy_fee=a.buy_fee_pct,
        sell_fee=a.sell_fee_pct,
        min_support=a.min_support,
        min_unique_days=a.min_unique_days,
        top_each=a.top_each,
        top_formulas=a.top_formulas,
    )
    Path(a.output).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

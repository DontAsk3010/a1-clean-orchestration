from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .mg_formula_candidate_spec import spec_from_v5_candidate, to_afl_boolean_expression


def choose_rows(report: Mapping[str, Any], *, strict_only: bool = True, limit: int = 10) -> list[Mapping[str, Any]]:
    rows = list(report.get("candidate_table") or [])
    if strict_only:
        rows = [r for r in rows if bool(r.get("strict_q25_cross_period_pass"))]
    else:
        rows = [r for r in rows if bool(r.get("cross_period_pass"))]
    return rows[: max(0, int(limit))]


def freeze_report(report: Mapping[str, Any], *, strict_only: bool = True, limit: int = 10) -> dict[str, Any]:
    if report.get("schema") != "A1_TELEGRAM_MG_OUTCOME_FIRST_DISCOVERY_V5":
        raise ValueError("UNSUPPORTED_V5_REPORT_SCHEMA")
    if report.get("march_2025_oos_touched") is not False:
        raise ValueError("OOS_INTEGRITY_NOT_PROVEN")
    if report.get("future_data_used_for_formula_state") is not False:
        raise ValueError("FORMULA_STATE_FUTURE_LEAKAGE")

    selected = choose_rows(report, strict_only=strict_only, limit=limit)
    frozen = []
    for idx, row in enumerate(selected, start=1):
        formula_id = f"MG_V5_{idx:03d}"
        spec = spec_from_v5_candidate(row, formula_id=formula_id)
        frozen.append({
            "spec": spec.to_dict(),
            "afl_boolean_expression": to_afl_boolean_expression(spec),
            "validation_evidence": {
                "cross_period_pass": bool(row.get("cross_period_pass")),
                "strict_q25_cross_period_pass": bool(row.get("strict_q25_cross_period_pass")),
                "min_period_q25_net_mfe": row.get("min_period_q25_net_mfe"),
                "min_period_median_net_mfe": row.get("min_period_median_net_mfe"),
                "min_period_positive_rate": row.get("min_period_positive_rate"),
                "total_evaluable": row.get("total_evaluable"),
            },
        })

    return {
        "schema": "A1_TELEGRAM_MG_FROZEN_CANDIDATE_PACK_V1",
        "status": "RESEARCH_CANDIDATE_NOT_CANONICAL",
        "source_schema": report.get("schema"),
        "source_request_id": report.get("request_id"),
        "strict_only": strict_only,
        "formula_count": len(frozen),
        "formulas": frozen,
        "runtime_rule": "CAUSAL_MARKERS_ONLY__FIRST_MATCH_PER_TICKER_DAY",
        "future_data_in_executable_formula": False,
        "promotion_to_live_allowed": False,
    }


def write_afl(pack: Mapping[str, Any], path: Path) -> None:
    lines = [
        "// A1 CLEAN / QHPX — GENERATED MG V5 RESEARCH CANDIDATES",
        "// STATUS: RESEARCH_CANDIDATE_NOT_CANONICAL",
        "// Every S_* input must be parity-bound before AmiBroker parity is claimed.",
        "",
    ]
    for row in pack.get("formulas", []):
        spec = row["spec"]
        lines.append(f"{spec['formula_id']} = {row['afl_boolean_expression']};")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="a1clean-mg-v5-candidate-freezer")
    p.add_argument("--input", required=True)
    p.add_argument("--output-json", required=True)
    p.add_argument("--output-afl", required=True)
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--allow-nonstrict", action="store_true")
    a = p.parse_args(argv)

    report = json.loads(Path(a.input).read_text(encoding="utf-8"))
    pack = freeze_report(report, strict_only=not a.allow_nonstrict, limit=a.limit)
    Path(a.output_json).write_text(json.dumps(pack, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_afl(pack, Path(a.output_afl))
    print(json.dumps({"pass": True, "formula_count": pack["formula_count"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

DEFAULT_KEYS = ("Ticker", "DateTime")
DEFAULT_BOOLEAN_COLUMNS = (
    "P01_WAKE_RESPONSE_RETENTION",
    "P02_RECOVERY_RECLAIM",
    "P03_COMPRESSION_EXPANSION",
    "P04_PULLBACK_REACCELERATION",
    "P05_FLOW_RESILIENT_CONTINUATION",
    "P06_EARLY_STRENGTH_RETAINED",
    "N01_BUY_STALL_TRAP",
    "N02_LATE_CHASE_TRAP",
    "N03_STRUCTURE_FAILURE",
    "N04_DATA_OR_SESSION_BLOCK",
    "MG_BEHAVIOR_CANDIDATE",
    "MG_EXECUTION_CANDIDATE",
    "MG_PROFIT_QUALIFIED",
)


def _truth(value: Any) -> bool | None:
    if value is None:
        return None
    s = str(value).strip().upper()
    if s in {"1", "1.0", "TRUE", "T", "YES"}:
        return True
    if s in {"0", "0.0", "FALSE", "F", "NO"}:
        return False
    if s in {"", "NULL", "NONE", "N/A", "NA"}:
        return None
    raise ValueError(f"UNRECOGNIZED_BOOLEAN:{value}")


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def compare_rows(
    python_rows: Iterable[dict[str, Any]],
    ami_rows: Iterable[dict[str, Any]],
    *,
    keys: Sequence[str] = DEFAULT_KEYS,
    boolean_columns: Sequence[str] = DEFAULT_BOOLEAN_COLUMNS,
) -> dict[str, Any]:
    def index(rows: Iterable[dict[str, Any]]) -> dict[tuple[str, ...], dict[str, Any]]:
        out: dict[tuple[str, ...], dict[str, Any]] = {}
        for row in rows:
            key = tuple(str(row.get(k, "")).strip() for k in keys)
            if key in out:
                raise ValueError(f"DUPLICATE_PARITY_KEY:{key}")
            out[key] = row
        return out

    py = index(python_rows)
    ami = index(ami_rows)
    all_keys = sorted(set(py) | set(ami))
    missing_in_ami = [k for k in all_keys if k not in ami]
    missing_in_python = [k for k in all_keys if k not in py]
    mismatches: list[dict[str, Any]] = []

    for key in all_keys:
        if key not in py or key not in ami:
            continue
        for col in boolean_columns:
            pv = _truth(py[key].get(col))
            av = _truth(ami[key].get(col))
            if pv != av:
                mismatches.append({"key": key, "column": col, "python": pv, "amibroker": av})

    return {
        "pass": not missing_in_ami and not missing_in_python and not mismatches,
        "python_row_count": len(py),
        "amibroker_row_count": len(ami),
        "missing_in_amibroker": missing_in_ami,
        "missing_in_python": missing_in_python,
        "boolean_mismatch_count": len(mismatches),
        "boolean_mismatches": mismatches[:500],
        "keys": list(keys),
        "boolean_columns": list(boolean_columns),
    }


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="a1clean-amibroker-parity-compare")
    p.add_argument("--python-csv", required=True)
    p.add_argument("--amibroker-csv", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--key", action="append")
    p.add_argument("--boolean-column", action="append")
    a = p.parse_args(argv)
    result = compare_rows(
        _read_csv(a.python_csv),
        _read_csv(a.amibroker_csv),
        keys=tuple(a.key) if a.key else DEFAULT_KEYS,
        boolean_columns=tuple(a.boolean_column) if a.boolean_column else DEFAULT_BOOLEAN_COLUMNS,
    )
    Path(a.output).write_text(json.dumps(result, indent=2, default=list) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, default=list))
    return 0 if result["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

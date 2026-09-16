from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from .haka_haki_reconstruction import reconstruct_bar


def _f(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _safe_div(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return a / b


def enrich_formation_chronology(bars: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Add source-bound HAKA/HAKI chronology without converting it into a signal.

    Unknown/unavailable rows stay unknown.  The output intentionally preserves
    continuous amounts, shares, change and price response so later mining can
    discover sequence structure empirically rather than begin from thresholds.
    """
    out: list[dict[str, Any]] = []
    prev_close: float | None = None
    prev_haka: float | None = None
    prev_haki: float | None = None
    cum_haka = 0.0
    cum_haki = 0.0
    valid_rows = 0
    observed_rows = 0

    for bar in bars:
        observed_rows += 1
        close = _f(bar.get("close"))
        rec = reconstruct_bar(bar)
        haka = _f(rec.get("haka"))
        haki = _f(rec.get("haki"))
        value = _f(rec.get("trade_value"))
        nbss = _f(rec.get("nbss"))

        price_delta_pct = None
        if close is not None and prev_close not in (None, 0):
            price_delta_pct = (close / float(prev_close) - 1.0) * 100.0

        row = dict(bar)
        row.update({
            "haka_haki_reconstruction_status": rec["status"],
            "haka": haka,
            "haki": haki,
            "haka_share_of_trade_value": _safe_div(haka, value),
            "haki_share_of_trade_value": _safe_div(haki, value),
            "nbss_to_trade_value": _safe_div(nbss, value) if haka is not None and haki is not None else None,
            "two_sided_effort_fraction": (
                _safe_div(2.0 * min(haka, haki), haka + haki)
                if haka is not None and haki is not None and haka + haki > 0
                else None
            ),
            "price_delta_pct": price_delta_pct,
            "haka_delta": None if haka is None or prev_haka is None else haka - prev_haka,
            "haki_delta": None if haki is None or prev_haki is None else haki - prev_haki,
            "cum_haka": None,
            "cum_haki": None,
            "formation_coverage_fraction": None,
        })

        if haka is not None and haki is not None:
            valid_rows += 1
            cum_haka += haka
            cum_haki += haki
            row["cum_haka"] = cum_haka
            row["cum_haki"] = cum_haki
            row["formation_coverage_fraction"] = valid_rows / observed_rows
            prev_haka = haka
            prev_haki = haki
        elif observed_rows:
            row["formation_coverage_fraction"] = valid_rows / observed_rows

        out.append(row)
        if close is not None:
            prev_close = close

    return out


def formation_window_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize a causal window while retaining unknown coverage explicitly."""
    if not rows:
        return {
            "observed_rows": 0,
            "valid_haka_haki_rows": 0,
            "coverage_fraction": None,
            "haka": None,
            "haki": None,
            "trade_value": None,
            "nbss": None,
        }

    valid = [
        r for r in rows
        if _f(r.get("haka")) is not None and _f(r.get("haki")) is not None
    ]
    if not valid:
        return {
            "observed_rows": len(rows),
            "valid_haka_haki_rows": 0,
            "coverage_fraction": 0.0,
            "haka": None,
            "haki": None,
            "trade_value": None,
            "nbss": None,
        }

    haka = sum(float(r["haka"]) for r in valid)
    haki = sum(float(r["haki"]) for r in valid)
    trade_value = haka + haki
    nbss = haka - haki
    closes = [_f(r.get("close")) for r in rows]
    closes = [x for x in closes if x is not None]
    price_path_pct = None
    if len(closes) >= 2 and closes[0] != 0:
        price_path_pct = (closes[-1] / closes[0] - 1.0) * 100.0

    return {
        "observed_rows": len(rows),
        "valid_haka_haki_rows": len(valid),
        "coverage_fraction": len(valid) / len(rows),
        "haka": haka,
        "haki": haki,
        "trade_value": trade_value,
        "nbss": nbss,
        "haka_share_of_trade_value": _safe_div(haka, trade_value),
        "haki_share_of_trade_value": _safe_div(haki, trade_value),
        "two_sided_effort_fraction": _safe_div(2.0 * min(haka, haki), trade_value),
        "price_path_pct": price_path_pct,
        "formation_price_joint_vector": {
            "haka": haka,
            "haki": haki,
            "nbss": nbss,
            "trade_value": trade_value,
            "price_path_pct": price_path_pct,
        },
    }

from __future__ import annotations

import pytest

from a1clean.formula_research.claude_openlow_pattern_mining_v1 import (
    FEATURES,
    _bucket_of,
    _mine_cells,
    _profile,
    _quantile_edges,
    render,
)


def _row(chg, bar, prior_range, reached, **kw):
    base = {
        "chg_at_signal_pct": chg,
        "bar_index": float(bar),
        "prior_day_range_pct": prior_range,
        "day_range_so_far_pct": 5.0,
        "value_expansion": 2.0,
        "close_location": 0.9,
        "price": 500.0,
        "prior_day_return_pct": 1.0,
        "reached_target": reached,
        # Mining ranks on money now, so every row carries a rupiah result.
        # The default ties it to the label only so existing shape tests stay
        # readable; tests about money set it explicitly.
        "pl_eod_rp": 250_000.0 if reached else -150_000.0,
        "max_profit_rp": 400_000.0 if reached else 50_000.0,
    }
    base.update(kw)
    return base


def test_price_tier_is_mined_since_idx_behaviour_differs_by_price_band():
    assert "price" in FEATURES
    assert "prior_day_return_pct" in FEATURES


def test_quantile_edges_collapse_duplicates_so_spiky_data_makes_no_empty_cells():
    assert _quantile_edges([5.0] * 20, 5) == [5.0]
    edges = _quantile_edges(list(range(100)), 5)
    assert edges == sorted(set(edges))
    assert len(edges) == 4


def test_bucket_assignment_is_ordered_and_handles_missing_values():
    edges = [10.0, 20.0, 30.0]
    assert _bucket_of(5.0, edges) == 0
    assert _bucket_of(10.0, edges) == 0
    assert _bucket_of(15.0, edges) == 1
    assert _bucket_of(99.0, edges) == 3
    assert _bucket_of(None, edges) is None


def test_profile_exposes_shape_not_just_a_mean():
    """A threshold relationship must show as a jump between buckets."""
    rows = [_row(chg, 3, 5.0, chg >= 8.0) for chg in [4, 4, 5, 5, 6, 6, 9, 9, 10, 10]]
    prof = _profile(rows, "chg_at_signal_pct", 5)
    assert prof["usable"]
    ps = [b["p_reach_target"] for b in prof["buckets"]]
    assert ps[0] == 0.0 and ps[-1] == 1.0


def test_profile_reports_unusable_rather_than_inventing_buckets():
    prof = _profile([_row(4, 3, None, False)], "prior_day_range_pct", 5)
    assert prof["usable"] is False


def test_mined_cells_respect_the_support_floor():
    rows = [_row(4, 3, 5.0, False) for _ in range(5)] + [_row(12, 2, 15.0, True) for _ in range(40)]
    cells = _mine_cells(rows, ("chg_at_signal_pct", "prior_day_range_pct"),
                        buckets=2, min_support=20, max_combo=2)
    assert cells
    assert all(c["support"] >= 20 for c in cells)


def test_lift_is_measured_against_the_population_base_rate():
    # Unequal counts so the median edge falls between the two groups rather than
    # on the upper value, which would put both groups in one bucket.
    rows = [_row(4, 3, 5.0, False) for _ in range(60)] + [_row(12, 2, 15.0, True) for _ in range(40)]
    cells = _mine_cells(rows, ("chg_at_signal_pct", "prior_day_range_pct"),
                        buckets=2, min_support=10, max_combo=2)
    best = cells[0]
    assert best["p_reach_target"] == pytest.approx(1.0)
    # base rate is 0.4, so a perfect cell lifts by +60pp
    assert best["lift_pp"] == pytest.approx(60.0)


def test_cells_carry_the_ranges_that_become_the_boundary():
    rows = [_row(12, 2, 15.0, True) for _ in range(30)]
    cells = _mine_cells(rows, ("chg_at_signal_pct", "prior_day_range_pct"),
                        buckets=2, min_support=10, max_combo=2)
    assert cells[0]["feature_ranges"]["chg_at_signal_pct"] == [12.0, 12.0]


def test_render_states_plainly_when_there_is_nothing_to_mine():
    assert "nothing to mine" in render({"signals": 0, "source_name": "X"}, top_cells=5)


def test_slot_grid_covers_every_publication_slot_from_the_open():
    from a1clean.formula_research.claude_openlow_pattern_mining_v1 import _slot_grid

    assert _slot_grid("09:00", "09:20", 5) == ["09:00", "09:05", "09:10", "09:15", "09:20"]
    assert _slot_grid("09:00", "09:00", 5) == ["09:00"]


def test_empty_slots_render_the_zero_match_symbol_and_never_vanish():
    """The owner's requirement and Sub-Sub Master section 7 agree: every slot
    from 09:00 is reported, screened or not, so an empty slot cannot be
    mistaken for an outage."""
    from a1clean.formula_research.claude_openlow_pattern_mining_v1 import render_screening_feed

    payload = {
        "source_name": "X",
        "signal_rows": [
            {"date": "2024-12-03", "slot": "09:00", "ticker": "AAAA", "price": 234.0,
             "chg_at_signal_pct": 3.54},
            {"date": "2024-12-03", "slot": "09:10", "ticker": "BBBB", "price": 1780.0,
             "chg_at_signal_pct": 7.03},
        ],
    }
    text = render_screening_feed(payload)
    assert "[09:00] AAAA" in text
    assert "[09:05] ========" in text
    assert "[09:10] BBBB" in text


def test_several_tickers_share_one_slot_rather_than_taking_a_line_each():
    from a1clean.formula_research.claude_openlow_pattern_mining_v1 import render_screening_feed

    payload = {
        "source_name": "X",
        "signal_rows": [
            {"date": "2024-12-03", "slot": "09:00", "ticker": "BBBB", "price": 100.0,
             "chg_at_signal_pct": 5.0},
            {"date": "2024-12-03", "slot": "09:00", "ticker": "AAAA", "price": 200.0,
             "chg_at_signal_pct": 4.0},
        ],
    }
    line = [l for l in render_screening_feed(payload).splitlines() if l.startswith("[09:00]")][0]
    assert line.index("AAAA") < line.index("BBBB")  # sorted within the slot


def test_a_slot_publishes_each_code_once_not_once_per_minute_bar():
    """A 5-minute slot holds five 1-minute bars. The first run's feed printed
    'AKRA ... AKRA ... AKRA' because every qualifying bar became its own entry;
    the contract publishes one CODE per snapshot."""
    from a1clean.formula_research.claude_openlow_pattern_mining_v1 import render_screening_feed

    payload = {
        "source_name": "Raw Des 02-31-2024.csv",
        "signal_rows": [
            {"date": "2024-12-03", "slot": "09:00", "ticker": "AKRA", "price": 1270.0,
             "chg_at_signal_pct": 3.67, "first_detectable_time": "09:01"},
            {"date": "2024-12-03", "slot": "09:00", "ticker": "AKRA", "price": 1275.0,
             "chg_at_signal_pct": 4.08, "first_detectable_time": "09:04"},
            {"date": "2024-12-03", "slot": "09:00", "ticker": "AWAN", "price": 326.0,
             "chg_at_signal_pct": 4.49, "first_detectable_time": "09:02"},
        ],
    }
    text = render_screening_feed(payload)
    slot_line = next(ln for ln in text.splitlines() if ln.startswith("[09:00]"))
    assert slot_line.count("AKRA") == 1
    assert slot_line.count("AWAN") == 1
    # The snapshot reports the state at its last bar, so 1.275 wins over 1.270.
    assert "1.275" in slot_line and "1.270" not in slot_line


def test_cells_are_ranked_by_money_not_by_touch_probability():
    """Entry 016: a touch threshold that overlaps the entry condition cannot
    fail. Ranking cells on P(reach target) would rediscover that illusion in
    cell form, so the ranking key must be rupiah."""
    from a1clean.formula_research.claude_openlow_pattern_mining_v1 import _mine_cells

    rows = []
    # Group A: always "reaches target" but bleeds money -- the Entry 016 trap.
    # Values are spread, not repeated: a bucketer fed one constant per group
    # collapses both into a single cell and the test would prove nothing.
    for i in range(30):
        rows.append(_row(8.0 + i * 0.1, 1 + i % 3, 9.0, True,
                         pl_eod_rp=-400_000.0, max_profit_rp=0.0))
    # Group B: reaches target less often but actually pays.
    for i in range(30):
        rows.append(_row(3.0 + i * 0.1, 11 + i % 3, 4.0, False,
                         pl_eod_rp=350_000.0, max_profit_rp=600_000.0))

    cells = _mine_cells(rows, ("chg_at_signal_pct", "bar_index"), buckets=2,
                        min_support=10, max_combo=2)
    assert cells, "expected at least one cell to clear the support floor"
    best = cells[0]
    assert best["mean_pl_rp"] > 0
    # The money-losing group scores a perfect touch rate and must still lose.
    assert best["p_reach_target"] < 1.0
    assert best["p_profitable"] == 1.0


def test_a_bucket_reports_what_it_paid_not_only_how_often_it_touched():
    from a1clean.formula_research.claude_openlow_pattern_mining_v1 import _profile

    rows = [_row(1.0 + i * 0.5, 5, 5.0, i > 10, pl_eod_rp=(i - 10) * 50_000.0) for i in range(20)]
    prof = _profile(rows, "chg_at_signal_pct", 2)
    assert prof["usable"]
    for bucket in prof["buckets"]:
        assert "mean_pl_rp" in bucket and "p_profitable" in bucket and "total_pl_rp" in bucket
    lo, hi = prof["buckets"][0], prof["buckets"][-1]
    assert lo["mean_pl_rp"] < hi["mean_pl_rp"]


def test_cli_accepts_every_flag_the_workflow_passes():
    """Run 35122982338 died in two seconds on 'unrecognized arguments:
    --capital-per-signal' because a patch to the parser silently missed while
    the call site already used it. The parser and the workflow must agree."""
    import re
    from pathlib import Path
    from a1clean.formula_research import claude_openlow_pattern_mining_v1 as mod

    workflow = Path(__file__).resolve().parents[1] / ".github/workflows/claude-mg-openlow-mining.yml"
    passed = set(re.findall(r"(--[a-z][a-z0-9-]+)", workflow.read_text(encoding="utf-8")))
    parser_src = mod.main.__doc__ or ""
    defined = set(re.findall(r'add_argument\("(--[a-z0-9-]+)"',
                             Path(mod.__file__).read_text(encoding="utf-8")))
    missing = {f for f in passed if f.startswith("--") and f in {
        "--source-name", "--min-chg-pct", "--strength-target-pct", "--buckets",
        "--min-support", "--max-combo", "--top-cells", "--output", "--report-output",
        "--feed-output", "--from-time", "--slot-minutes", "--capital-per-signal",
    }} - defined
    assert not missing, f"workflow passes flags the parser does not define: {sorted(missing)}"
    assert parser_src is not None

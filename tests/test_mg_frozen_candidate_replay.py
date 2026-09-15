import a1clean.formula_research.mg_frozen_candidate_replay as mod
from a1clean.formula_research.handbook_candidates import CandidateParams


def _params():
    return CandidateParams(
        effort_lookback=5,
        progress_lookback=5,
        high_lookback=5,
        recovery_lookback=10,
        low_stabilization_bars=3,
        early_checkpoint_bar=30,
        late_lift_min_bar=180,
    )


def _pack():
    return {
        "schema": "A1_TELEGRAM_MG_FROZEN_CANDIDATE_PACK_V1",
        "future_data_in_executable_formula": False,
        "formulas": [
            {
                "spec": {
                    "formula_id": "MG_X",
                    "required": ["CUR_FLOW", "PRIOR3_RECLAIM"],
                    "forbidden": [],
                }
            }
        ],
    }


def test_replay_pack_uses_first_match_scanner_and_returns_period_metrics(monkeypatch):
    def fake_scan_source(**kwargs):
        assert kwargs["candidate_parts"] == {"MG_X": ("CUR_FLOW", "PRIOR3_RECLAIM")}
        return (
            {
                "MG_X": [
                    {
                        "source": "S1",
                        "evaluable": True,
                        "net_mfe_pct": 1.0,
                        "mae_pct": -0.2,
                        "eod_net_pct": 0.4,
                    }
                ]
            },
            [],
            {"S1": 10},
        )

    monkeypatch.setattr(mod, "_scan_source", fake_scan_source)
    r = mod.replay_pack(
        _pack(),
        source_names=["S1"],
        params=_params(),
        prior_window=2,
        buy_fee_pct=0.15,
        sell_fee_pct=0.25,
    )
    assert r["formula_count"] == 1
    assert r["formulas"]["MG_X"]["by_period"]["S1"]["positive_net_mfe_rate"] == 1.0
    assert r["future_data_used_for_formula_state"] is False


def test_replay_rejects_forbidden_marker_until_scanner_support_exists():
    pack = _pack()
    pack["formulas"][0]["spec"]["forbidden"] = ["TIME_14_PLUS"]
    try:
        mod.replay_pack(
            pack,
            source_names=["S1"],
            params=_params(),
            prior_window=2,
            buy_fee_pct=0.15,
            sell_fee_pct=0.25,
        )
    except ValueError as e:
        assert str(e) == "FORBIDDEN_MARKER_REPLAY_NOT_IMPLEMENTED"
    else:
        raise AssertionError("expected explicit forbidden-marker rejection")

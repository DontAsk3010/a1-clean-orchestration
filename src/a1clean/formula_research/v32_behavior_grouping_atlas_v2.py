from __future__ import annotations

import gzip
import json
import os
from collections import Counter, defaultdict
from datetime import datetime
from itertools import zip_longest
from pathlib import Path
from typing import Any, Mapping

from . import v32_behavior_grouping_atlas as base

SCHEMA = "A1_V32_BEHAVIOR_GROUPING_ATLAS_V2"
AXIS_VERSION = "M2_MULTI_AXIS_EXACT_SIGNATURE_TEMPORAL_BLINDSPOT_V2"
STATUS = base.STATUS
FORMULA_STAGE = base.FORMULA_STAGE
SEMANTIC_SCHEMA = base.SEMANTIC_SCHEMA

REQUIRED_CURRENT_STAGE_AXES = (
    "FULL_STATE_SEQUENCE","PRICE_PATH","VOLUME_PATH","VALUE_PATH","FLOW_DIRECTION_PATH",
    "FLOW_EFFORT_PATH","FLOW_PRICE_RESPONSE_PATH","RANGE_PATH","OPEN_STATE_PATH","HAKA_HAKI_PATH",
    "FRESH_EXTREME_PATH","TRANSITION_DIMENSION_PATH","JOURNEY_KIND_SEQUENCE","CENSOR_STATE_SEQUENCE",
    "NO_FORCED_EVENT_STATE","EVIDENCE_AVAILABILITY","SOURCE_PHASE_PRESENCE","CROSS_DATE_CARRY_PRESENT",
    "SOURCE_TERMINAL_PHASE","STATE_ORDER","TRANSITION_ORDER","STATE_RUN_TIMING_PROFILE","TIME_OF_DAY",
    "SESSION_PHASE","DURATION_PROFILE","PERSISTENCE_PROFILE","TIMING_X_BEHAVIOR",
    "STATE_REAPPEARANCE_PROFILE","DIRECTIONAL_ASYMMETRY_PROFILE","EFFORT_RESPONSE_TRAJECTORY",
    "NEGATIVE_EVIDENCE_PATH","FRESH_EXTREME_ATTEMPT_PROFILE","OPEN_RELATION_ATTEMPT_PROFILE",
    "CROSS_DATE_TEMPORAL_CARRY","SOURCE_OBSERVATION_ENVELOPE","JOURNEY_KIND","JOURNEY_DIRECTIONAL_ROLE",
    "JOURNEY_FORMATION_SEQUENCE","JOURNEY_FORMATION_TEMPORAL_SEQUENCE","JOURNEY_EVENT_START_CLOCK",
    "JOURNEY_START_SOURCE_PHASE","JOURNEY_CAUSAL_TIMING_PROFILE","JOURNEY_DURATION_PROFILE",
    "JOURNEY_RESPONSE_LAG_PROFILE","JOURNEY_TIMESTAMP_DISCONTINUITY_PROFILE",
    "JOURNEY_TEMPORAL_CHAIN_PROFILE","JOURNEY_PRIOR_CONDITION_PROFILE","JOURNEY_OPEN_CENSOR_STATE",
    "HINDSIGHT_RESOLUTION_STATUS","HINDSIGHT_RESOLUTION_TIMING_PROFILE","FORMATION_X_HINDSIGHT_RESOLUTION",
)

DEFERRED_CROSS_CORPUS_STUDIES = (
    "SAME_TICKER_BEHAVIOR_HABIT_RECURRENCE","CROSS_TICKER_RECURRENCE","CROSS_DATE_RECURRENCE",
    "CROSS_MONTH_RECURRENCE","MARKET_DAY_RECURRENCE","RELATIVE_LIQUIDITY_REGIME",
    "MARKET_SECTOR_RELATIVE_CONTEXT","STRUCTURAL_BREAK_STABILITY","BASE_RATE_STABILITY",
    "CROSS_REGIME_STABILITY","NEAR_TWIN_DISCRIMINATOR_STUDY",
)
FUTURE_EVIDENCE_LANES = (
    "PARTICIPANT_BROKER_FLOW","TICK_TIME_AND_TRADE_AGGRESSOR","L1_BBO","L2_DEPTH_QUEUE_REFILL",
    "FOREIGN_DOMESTIC_PARTICIPANT_DETAIL_WHERE_NOT_ALREADY_SOURCE_PROVEN",
    "CORPORATE_ACTION_CONTEXT","ISSUER_EVENT_CONTEXT",
)
FUTURE_FORMULA_GATES = (
    "FROZEN_BEHAVIOR_ATLAS","NEAR_TWIN_NEGATIVE_CONTROL","CAUSAL_DISCRIMINATOR_STUDY",
    "ABLATION_INCREMENTAL_VALUE","TEMPORAL_STABILITY","CROSS_TICKER_STABILITY",
    "CROSS_MONTH_STABILITY","REGIME_STABILITY","EXECUTION_REALISM","FORMULA_FEATURE_ADMISSION",
)
NEGATIVE_RELATIONS = {"BUY_FLOW_PRICE_NON_RESPONSE_OR_ADVERSE","SELL_FLOW_PRICE_RESILIENCE"}


def _clock(value: Any) -> str:
    return base._clock(value)


def _parse_ts(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw or raw == "OPEN":
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _elapsed_seconds(start: Any, end: Any) -> int | float | str:
    s, e = _parse_ts(start), _parse_ts(end)
    if s is None or e is None:
        return "UNKNOWN"
    value = (e - s).total_seconds()
    return int(value) if value.is_integer() else value


def _regular_bars(rec: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not rec:
        return []
    bars = rec.get("bars")
    if not isinstance(bars, list):
        raise RuntimeError("M2_GROUP_REGULAR_STREAM_BARS_MISSING")
    return [dict(x) for x in bars]


def _bar_phase(bars: list[dict[str, Any]], index: Any) -> dict[str, str]:
    if not isinstance(index, int) or not (0 <= index < len(bars)):
        return {"source_phase":"UNKNOWN","session_code":"UNKNOWN","observation_role":"UNKNOWN"}
    b = bars[index]
    return {
        "source_phase": str(b.get("source_phase") or "UNKNOWN"),
        "session_code": str(b.get("idx_regular_clock_session_code") or "UNKNOWN"),
        "observation_role": str(b.get("observation_role") or "UNKNOWN"),
    }


def _run_timing(path_rec: Mapping[str, Any], bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for ordinal, run in enumerate(path_rec.get("formation_run_path") or [], 1):
        si, ei = run.get("start_index"), run.get("end_index")
        st, et = run.get("start_timestamp"), run.get("end_timestamp")
        out.append({
            "run_ordinal": ordinal,
            "state_key": str(run.get("state_key") or "UNKNOWN"),
            "start_index": si,"end_index": ei,
            "start_clock": _clock(st),"end_clock": _clock(et),
            "source_clock_elapsed_seconds": _elapsed_seconds(st, et),
            "row_count": int(run.get("row_count") or 0),
            "start_phase": _bar_phase(bars, si),"end_phase": _bar_phase(bars, ei),
        })
    return out


def _transition_order(path_rec: Mapping[str, Any]) -> list[dict[str, Any]]:
    out = []
    for t in path_rec.get("state_transitions") or []:
        out.append({
            "transition_ordinal": t.get("transition_ordinal"),
            "from_state_key": str(t.get("from_state_key") or "UNKNOWN"),
            "to_state_key": str(t.get("to_state_key") or "UNKNOWN"),
            "known_at_clock": _clock(t.get("known_at_time")),
            "changed_dimensions": sorted(str(x) for x in dict(t.get("changed_dimensions") or {})),
        })
    return out


def _reappearance(path_rec: Mapping[str, Any]) -> list[dict[str, Any]]:
    pos: dict[str, list[int]] = defaultdict(list)
    for ordinal, run in enumerate(path_rec.get("formation_run_path") or [], 1):
        pos[str(run.get("state_key") or "UNKNOWN")].append(ordinal)
    return [
        {"state_key": key,"occurrence_ordinals": ords,
         "run_ordinal_gaps": [b-a for a,b in zip(ords, ords[1:])]}
        for key, ords in sorted(pos.items()) if len(ords) > 1
    ]


def _directional_asymmetry(path_rec: Mapping[str, Any]) -> dict[str, Any]:
    rows, runs = Counter(), Counter()
    for run in path_rec.get("formation_run_path") or []:
        d = str(dict(run.get("state") or {}).get("price_direction") or "UNKNOWN")
        rows[d] += int(run.get("row_count") or 0); runs[d] += 1
    return {"row_counts_by_price_direction":dict(sorted(rows.items())),
            "run_counts_by_price_direction":dict(sorted(runs.items()))}


def _effort_response(path_rec: Mapping[str, Any]) -> list[dict[str, Any]]:
    out = []
    for run in path_rec.get("formation_run_path") or []:
        s = dict(run.get("state") or {})
        out.append({
            "flow_direction":s.get("flow_direction","UNKNOWN"),
            "flow_effort_change":s.get("flow_effort_change","UNKNOWN"),
            "flow_price_relation":s.get("flow_price_relation","UNKNOWN"),
            "price_direction":s.get("price_direction","UNKNOWN"),
            "value_activity_change":s.get("value_activity_change","UNKNOWN"),
            "bar_range_change":s.get("bar_range_change","UNKNOWN"),
            "row_count":int(run.get("row_count") or 0),
        })
    return out


def _negative_evidence(path_rec: Mapping[str, Any]) -> list[dict[str, Any]]:
    out = []
    for ordinal, run in enumerate(path_rec.get("formation_run_path") or [], 1):
        rel = str(dict(run.get("state") or {}).get("flow_price_relation") or "UNKNOWN")
        if rel in NEGATIVE_RELATIONS:
            out.append({"run_ordinal":ordinal,"relation":rel,"row_count":int(run.get("row_count") or 0)})
    return out


def _f(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _attempts(bars: list[dict[str, Any]]) -> tuple[list[Any], list[Any]]:
    ext, op = [], []
    rh = rl = None
    session_open = _f(bars[0].get("open")) if bars else None
    for i, b in enumerate(bars):
        hi, lo, close = _f(b.get("high")), _f(b.get("low")), _f(b.get("close"))
        if i == 0:
            hr = "FIRST_OBSERVATION" if hi is not None else "UNKNOWN"
            lr = "FIRST_OBSERVATION" if lo is not None else "UNKNOWN"
        else:
            hr = "UNKNOWN" if hi is None or rh is None else (
                "NEW_RUNNING_HIGH" if hi > rh else "EQUAL_RUNNING_HIGH_RETEST" if hi == rh else "BELOW_RUNNING_HIGH")
            lr = "UNKNOWN" if lo is None or rl is None else (
                "NEW_RUNNING_LOW" if lo < rl else "EQUAL_RUNNING_LOW_RETEST" if lo == rl else "ABOVE_RUNNING_LOW")
        ext.append([hr, lr])
        op.append("UNKNOWN" if close is None or session_open is None else (
            "ABOVE_SESSION_OPEN" if close > session_open else "BELOW_SESSION_OPEN" if close < session_open else "AT_SESSION_OPEN"))
        if hi is not None: rh = hi if rh is None else max(rh, hi)
        if lo is not None: rl = lo if rl is None else min(rl, lo)
    return base._compress(ext), base._compress(op)


def _carry(path_rec: Mapping[str, Any]) -> dict[str, Any]:
    c = dict(path_rec.get("prior_condition_carry") or {})
    first = dict(path_rec.get("first_regular_observation") or {})
    pts = ((c.get("last_source_supported_observation_state") or {}).get("timestamp")
           or c.get("known_at_boundary") or c.get("last_timestamp"))
    cts = first.get("timestamp")
    return {
        "present":bool(c),"status":str(c.get("status") or ("PRESENT" if c else "NONE")),
        "previous_governed_date":c.get("previous_governed_date"),
        "prior_terminal_clock":_clock(pts) if pts else "UNKNOWN",
        "current_first_clock":_clock(cts) if cts else "UNKNOWN",
        "source_clock_elapsed_seconds_across_date_boundary":_elapsed_seconds(pts, cts),
        "previous_terminal_phase":str(c.get("previous_terminal_observation_phase") or "UNKNOWN"),
    }


def _envelope(path_rec: Mapping[str, Any], td: Mapping[str, Any]) -> dict[str, Any]:
    fr = dict(path_rec.get("first_regular_observation") or {})
    lr = dict(path_rec.get("last_regular_observation") or {})
    ls = dict(path_rec.get("last_source_supported_observation") or {})
    return {
        "source_observation_count":int(td.get("source_observation_count") or 0),
        "regular_bar_count":int(td.get("regular_bar_count") or td.get("bar_count") or 0),
        "nonregular_context_observation_count":int(td.get("nonregular_context_observation_count") or 0),
        "first_regular_clock":_clock(fr.get("timestamp")),"last_regular_clock":_clock(lr.get("timestamp")),
        "last_source_clock":_clock(ls.get("timestamp")),"last_source_phase":str(ls.get("source_phase") or "UNKNOWN"),
    }


def _day_axes(path_rec: Mapping[str, Any], td: Mapping[str, Any], regular_rec: Mapping[str, Any] | None = None) -> dict[str, Any]:
    axes = dict(base._day_axes(path_rec, td))
    refs, bars = list(path_rec.get("lifecycle_journey_refs") or []), _regular_bars(regular_rec)
    rt = _run_timing(path_rec, bars)
    extreme_attempts, open_attempts = _attempts(bars)
    axes.update({
        "STATE_ORDER":base._full_state_path(path_rec),
        "TRANSITION_ORDER":_transition_order(path_rec),
        "STATE_RUN_TIMING_PROFILE":rt,
        "TIME_OF_DAY":{"run_start_clocks":[x["start_clock"] for x in rt],
                       "journey_start_clocks":[_clock(x.get("event_start_time")) for x in refs]},
        "SESSION_PHASE":[{"run_ordinal":x["run_ordinal"],"start_phase":x["start_phase"],"end_phase":x["end_phase"]} for x in rt],
        "DURATION_PROFILE":[{"run_ordinal":x["run_ordinal"],"row_count":x["row_count"],
                             "source_clock_elapsed_seconds":x["source_clock_elapsed_seconds"]} for x in rt],
        "PERSISTENCE_PROFILE":[{"state_key":x["state_key"],"row_count":x["row_count"]} for x in rt],
        "TIMING_X_BEHAVIOR":[{"state_key":x["state_key"],"start_clock":x["start_clock"],"end_clock":x["end_clock"],
                              "row_count":x["row_count"],"start_phase":x["start_phase"]["source_phase"],
                              "end_phase":x["end_phase"]["source_phase"]} for x in rt],
        "STATE_REAPPEARANCE_PROFILE":_reappearance(path_rec),
        "DIRECTIONAL_ASYMMETRY_PROFILE":_directional_asymmetry(path_rec),
        "EFFORT_RESPONSE_TRAJECTORY":_effort_response(path_rec),
        "NEGATIVE_EVIDENCE_PATH":_negative_evidence(path_rec),
        "FRESH_EXTREME_ATTEMPT_PROFILE":extreme_attempts,
        "OPEN_RELATION_ATTEMPT_PROFILE":open_attempts,
        "CROSS_DATE_TEMPORAL_CARRY":_carry(path_rec),
        "SOURCE_OBSERVATION_ENVELOPE":_envelope(path_rec, td),
    })
    return axes


def _formation_structural(rec: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [{"role":str(x.get("role") or "UNKNOWN"),"state_key":str(x.get("state_key") or "UNKNOWN")}
            for x in rec.get("formation_sequence") or []]


def _formation_temporal(rec: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [{
        "role":str(x.get("role") or "UNKNOWN"),"state_key":str(x.get("state_key") or "UNKNOWN"),
        "start_clock":_clock(x.get("start_timestamp")),"end_clock":_clock(x.get("end_timestamp")),
        "row_count":int(x.get("row_count") or 0),"start_index":x.get("start_index"),"end_index":x.get("end_index"),
        "source_clock_elapsed_seconds":_elapsed_seconds(x.get("start_timestamp"),x.get("end_timestamp")),
    } for x in rec.get("formation_sequence") or []]


def _causal_timing(rec: Mapping[str, Any]) -> dict[str, Any]:
    t = dict(rec.get("timing") or {})
    names = ("precursor_start_time","first_observed_time","event_start_time","first_detectable_time",
             "change_point_time","known_at_time","confirm_time","peak_time","trough_time","extreme_time","weakening_time")
    return {n:(_clock(t.get(n)) if t.get(n) else "UNKNOWN") for n in names}


def _response_lag(rec: Mapping[str, Any]) -> dict[str, Any]:
    t = dict(rec.get("timing") or {}); st = t.get("event_start_time")
    return {"start_to_confirm_seconds":_elapsed_seconds(st,t.get("confirm_time")),
            "start_to_extreme_seconds":_elapsed_seconds(st,t.get("extreme_time")),
            "start_to_weakening_seconds":_elapsed_seconds(st,t.get("weakening_time"))}


def _duration(rec: Mapping[str, Any]) -> dict[str, Any]:
    t = dict(rec.get("timing") or {}); st, last, end = t.get("event_start_time"),t.get("last_observed_time"),t.get("event_end_time")
    return {"event_start_clock":_clock(st),"last_observed_clock":_clock(last),
            "event_end_clock":_clock(end) if end and end != "OPEN" else "OPEN",
            "start_to_last_observed_seconds":_elapsed_seconds(st,last),
            "start_to_event_end_seconds":_elapsed_seconds(st,end),
            "right_censored_open":bool(rec.get("right_censored_open"))}


def _prior(rec: Mapping[str, Any]) -> dict[str, Any]:
    p = dict(rec.get("prior_condition") or {}); rb = dict(p.get("regular_prior_bar") or {}); c = dict(p.get("cross_date_carry_if_start_at_first_regular_bar") or {})
    return {"regular_prior_bar_present":bool(rb),"regular_prior_clock":_clock(rb.get("timestamp")) if rb else "UNKNOWN",
            "cross_date_carry_present":bool(c),"cross_date_carry_status":str(c.get("status") or ("PRESENT" if c else "NONE")),
            "cross_date_previous_governed_date":c.get("previous_governed_date")}


def _lifecycle_axes(rec: Mapping[str, Any]) -> tuple[dict[str, Any], str, str, str]:
    formation, temporal = _formation_structural(rec), _formation_temporal(rec)
    resolution = str((rec.get("hindsight_resolution") or {}).get("resolution_status") or "UNKNOWN")
    start_evidence = dict((rec.get("critical_evidence") or {}).get("event_start") or {})
    dna = {
        "journey_kind":str(rec.get("journey_kind") or "UNKNOWN"),
        "directional_role":str(rec.get("directional_role") or "UNKNOWN"),
        "formation_sequence":formation,"formation_temporal_sequence":temporal,
        "event_start_clock":_clock((rec.get("timing") or {}).get("event_start_time")),
        "event_start_source_phase":str(start_evidence.get("source_phase") or "UNKNOWN"),
        "causal_timing_profile":_causal_timing(rec),"response_lag_profile":_response_lag(rec),
        "open_censor_state":bool(rec.get("right_censored_open")),
    }
    axes = {
        "JOURNEY_KIND":dna["journey_kind"],"JOURNEY_DIRECTIONAL_ROLE":dna["directional_role"],
        "JOURNEY_FORMATION_SEQUENCE":formation,"JOURNEY_FORMATION_TEMPORAL_SEQUENCE":temporal,
        "JOURNEY_EVENT_START_CLOCK":dna["event_start_clock"],"JOURNEY_START_SOURCE_PHASE":dna["event_start_source_phase"],
        "JOURNEY_CAUSAL_TIMING_PROFILE":dna["causal_timing_profile"],"JOURNEY_DURATION_PROFILE":_duration(rec),
        "JOURNEY_RESPONSE_LAG_PROFILE":dna["response_lag_profile"],
        "JOURNEY_TIMESTAMP_DISCONTINUITY_PROFILE":[{"delta_seconds":x.get("delta_seconds"),"interpretation":x.get("interpretation")} for x in rec.get("timestamp_discontinuities") or []],
        "JOURNEY_TEMPORAL_CHAIN_PROFILE":dict(rec.get("temporal_connected_chain") or {}),
        "JOURNEY_PRIOR_CONDITION_PROFILE":_prior(rec),"JOURNEY_OPEN_CENSOR_STATE":dna["open_censor_state"],
    }
    gid, sig = base._signature("CAUSAL_FORMATION_DNA", dna)
    return axes, gid, sig, resolution


def _hindsight_axes(rec: Mapping[str, Any], formation_id: str, resolution: str) -> dict[str, Any]:
    ro, t = dict(rec.get("hindsight_resolution") or {}), dict(rec.get("timing") or {})
    rt, st = ro.get("resolution_timestamp"), t.get("event_start_time")
    return {
        "HINDSIGHT_RESOLUTION_STATUS":resolution,
        "HINDSIGHT_RESOLUTION_TIMING_PROFILE":{
            "resolution_status":resolution,"right_censored":bool(ro.get("right_censored")),
            "resolution_clock":_clock(rt) if rt else "OPEN_OR_UNKNOWN",
            "start_to_resolution_seconds":_elapsed_seconds(st,rt),
            "fail_clock":_clock(t.get("fail_time")) if t.get("fail_time") else "UNKNOWN",
            "recovery_clock":_clock(t.get("recovery_time")) if t.get("recovery_time") else "UNKNOWN",
            "invalidation_clock":_clock(t.get("invalidation_time")) if t.get("invalidation_time") else "UNKNOWN",
        },
        "FORMATION_X_HINDSIGHT_RESOLUTION":{"causal_formation_group_id":formation_id,"resolution_status":resolution},
    }


def _build_contribution(*, source: str, source_order: int, source_dir: Path, cp: Mapping[str, Any],
                        cp_digest: str, contribution_dir: Path) -> dict[str, Any]:
    contribution_dir.mkdir(parents=True, exist_ok=True)
    manifest_path, db_path = contribution_dir/"contribution-manifest.json", contribution_dir/"contribution.sqlite3"
    day_path, journey_path = contribution_dir/"day-members.jsonl.gz", contribution_dir/"journey-members.jsonl.gz"
    if manifest_path.is_file() and db_path.is_file() and day_path.is_file() and journey_path.is_file():
        old = json.loads(manifest_path.read_text(encoding="utf-8"))
        if old.get("checkpoint_digest_sha256") == cp_digest and old.get("axis_version") == AXIS_VERSION and old.get("schema") == SCHEMA:
            return old
        raise RuntimeError(f"M2_GROUP_EXISTING_CONTRIBUTION_VERSION_OR_DIGEST_DRIFT:{source}")

    ticker_path = base._validate_input_file(source_dir, cp, "ticker_days")
    behavior_path = base._validate_input_file(source_dir, cp, "behavior_paths")
    lifecycle_path = base._validate_input_file(source_dir, cp, "behavior_lifecycle")
    regular_path = base._validate_input_file(source_dir, cp, "regular_behavior_stream")
    td = {(str(x.get("ticker")),str(x.get("date"))):x for x in base._iter_gz_jsonl(ticker_path)}
    expected_days = int(cp.get("ticker_days",-1))
    if len(td) != expected_days: raise RuntimeError(f"M2_GROUP_TICKER_DAY_INDEX_COUNT_FAIL:{source}:{len(td)}:{expected_days}")

    tdb, tday, tj = db_path.with_suffix(".sqlite3.tmp"), day_path.with_suffix(day_path.suffix+".tmp"), journey_path.with_suffix(journey_path.suffix+".tmp")
    for p in (tdb,tday,tj):
        if p.exists(): p.unlink()
    cdb = base._init_contribution_db(tdb); groups, near = Counter(), Counter(); dc = jc = 0
    try:
        with gzip.open(tday,"wt",encoding="utf-8",newline="\n") as fh:
            for pr, rr in zip_longest(base._iter_gz_jsonl(behavior_path),base._iter_gz_jsonl(regular_path)):
                if pr is None or rr is None: raise RuntimeError(f"M2_GROUP_REGULAR_STREAM_COUNT_DRIFT:{source}")
                key, rkey = (str(pr.get("ticker")),str(pr.get("date"))),(str(rr.get("ticker")),str(rr.get("date")))
                if key != rkey or str(rr.get("source") or "") != source: raise RuntimeError(f"M2_GROUP_REGULAR_STREAM_ORDER_DRIFT:{source}:{key}:{rkey}")
                if key not in td: raise RuntimeError(f"M2_GROUP_BEHAVIOR_PATH_ORPHAN:{source}:{key}")
                axes, mem = _day_axes(pr,td[key],rr), {}
                for axis,payload in axes.items():
                    gid,sig=base._signature(axis,payload); mem[axis]=gid; groups[(axis,gid,sig)]+=1
                fh.write(base._canon({"schema":SCHEMA,"axis_version":AXIS_VERSION,"source":source,"source_order":source_order,
                                      "ticker":key[0],"date":key[1],"causal_group_memberships":mem,
                                      "no_forced_event":bool(pr.get("no_forced_event")),"formula_stage":FORMULA_STAGE})+"\n")
                dc += 1
                if dc % 25000 == 0: base._flush_counts(cdb,groups,near); cdb.commit()
        with gzip.open(tj,"wt",encoding="utf-8",newline="\n") as fh:
            for rec in base._iter_gz_jsonl(lifecycle_path):
                axes,fid,fsig,res=_lifecycle_axes(rec); cmem={}
                for axis,payload in axes.items():
                    gid,sig=base._signature(axis,payload); cmem[axis]=gid; groups[(axis,gid,sig)]+=1
                hmem={}
                for axis,payload in _hindsight_axes(rec,fid,res).items():
                    gid,sig=base._signature(axis,payload); hmem[axis]=gid; groups[(axis,gid,sig)]+=1
                near[(fid,fsig,res)] += 1
                fh.write(base._canon({"schema":SCHEMA,"axis_version":AXIS_VERSION,"source":source,"source_order":source_order,
                                      "ticker":rec.get("ticker"),"date":rec.get("date"),"journey_id":rec.get("journey_id"),
                                      "journey_ordinal":rec.get("journey_ordinal"),"causal_group_memberships":cmem,
                                      "causal_formation_group_id":fid,"hindsight_group_memberships":hmem,
                                      "hindsight_resolution_status":res,"right_censored_open":bool(rec.get("right_censored_open")),
                                      "causal_and_hindsight_kept_separate":True,"formula_stage":FORMULA_STAGE})+"\n")
                jc += 1
                if jc % 25000 == 0: base._flush_counts(cdb,groups,near); cdb.commit()
        base._flush_counts(cdb,groups,near); cdb.commit()
    finally: cdb.close()

    if dc != int(cp.get("behavior_paths",expected_days)): raise RuntimeError(f"M2_GROUP_DAY_MEMBERSHIP_COUNT_FAIL:{source}:{dc}")
    if jc != int(cp.get("behavior_lifecycle_journeys",-1)): raise RuntimeError(f"M2_GROUP_JOURNEY_MEMBERSHIP_COUNT_FAIL:{source}:{jc}")
    os.replace(tdb,db_path); os.replace(tday,day_path); os.replace(tj,journey_path)
    m={"schema":SCHEMA,"axis_version":AXIS_VERSION,"status":"PASS_SOURCE_CONTRIBUTION","atlas_status":STATUS,
       "source":source,"source_order":source_order,"semantic_checkpoint_digest_sha256":cp_digest,
       "checkpoint_digest_sha256":cp_digest,"semantic_software_revision":cp.get("software_revision"),
       "source_drive_id":cp.get("source_drive_id"),"source_sha256":cp.get("source_sha256"),
       "ticker_day_memberships":dc,"journey_memberships":jc,"semantic_gaps_still_open":list(base.SEMANTIC_GAP_IDS),
       "machine1_labels_used":False,"arbitrary_thresholds_added":False,"missing_as_zero":False,"formula_stage":FORMULA_STAGE,
       "required_current_stage_axes":list(REQUIRED_CURRENT_STAGE_AXES),"deferred_cross_corpus_studies":list(DEFERRED_CROSS_CORPUS_STUDIES),
       "future_evidence_lanes":list(FUTURE_EVIDENCE_LANES),"future_formula_gates":list(FUTURE_FORMULA_GATES),
       "files":{"contribution_db":{"name":db_path.name,"sha256":base._sha_file(db_path),"bytes":db_path.stat().st_size},
                "day_members":{"name":day_path.name,"sha256":base._sha_file(day_path),"bytes":day_path.stat().st_size},
                "journey_members":{"name":journey_path.name,"sha256":base._sha_file(journey_path),"bytes":journey_path.stat().st_size}}}
    base._atomic_json(manifest_path,m); return m


_original_export = base._export_atlas
def _export_atlas(db, output_root: Path, software_revision: str) -> dict[str, Any]:
    m = _original_export(db,output_root,software_revision)
    summary = list(m.get("axis_summary") or [])
    present = {str(x.get("axis")) for x in summary}
    if m.get("source_count_consumed",0) and not set(REQUIRED_CURRENT_STAGE_AXES).issubset(present):
        missing=sorted(set(REQUIRED_CURRENT_STAGE_AXES)-present)
        raise RuntimeError("M2_GROUP_REQUIRED_AXIS_MISSING:"+",".join(missing))
    m.update({
        "schema":SCHEMA,"axis_version":AXIS_VERSION,"required_current_stage_axes":list(REQUIRED_CURRENT_STAGE_AXES),
        "required_current_stage_axes_present":not m.get("source_count_consumed",0) or set(REQUIRED_CURRENT_STAGE_AXES).issubset(present),
        "deferred_cross_corpus_studies":list(DEFERRED_CROSS_CORPUS_STUDIES),"future_evidence_lanes":list(FUTURE_EVIDENCE_LANES),
        "future_formula_gates":list(FUTURE_FORMULA_GATES),"coverage_contract_status":"PASS_CURRENT_STAGE_WITH_EXPLICIT_DEFERRED_GATES",
    })
    base._atomic_json(output_root/"manifest.json",m)
    cp=json.loads((output_root/"current-checkpoint.json").read_text(encoding="utf-8"))
    cp.update({"schema":SCHEMA,"axis_version":AXIS_VERSION,"coverage_contract_status":m["coverage_contract_status"]})
    base._atomic_json(output_root/"current-checkpoint.json",cp)
    return m


base.SCHEMA=SCHEMA
base.AXIS_VERSION=AXIS_VERSION
base._build_contribution=_build_contribution
base._export_atlas=_export_atlas
run_once=base.run_once


def main() -> None:
    base.main()


if __name__ == "__main__":
    main()

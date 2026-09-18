from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

from ..config import (
    FROZEN_CURRENT_FOLDER_DRIVE_ID,
    FROZEN_GENERATION_ID,
    FROZEN_IMPL_VERSION,
    FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID,
    FROZEN_RAW_FOLDER_DRIVE_ID,
    DataPlaneConfig,
)
from ..frozen_v2 import run_delta
from ..google_drive import build_drive_api
from ..pattern_discovery.packet import parse_semantic_packet
from ..source_parity import _SingleSourceDriveApi
from .formula_replay import packet_to_formula_bars
from .full_chronological_cache_catalog import (
    _canonical_raw_items,
    _download_raw_to_stage,
    _hash_file,
)

SOURCE = "Raw Des 02-31-2024.csv"
TICKER = "AALI"
TRADING_DATE = "2024-12-02"
TARGET_CLOCKS = {"08:59:00", "09:00:00", "15:49:00", "16:00:00", "16:01:00"}


def _exact_local_raw(item: dict[str, Any]) -> Path:
    expected_size = int(item.get("size") or -1)
    expected_md5 = str(item.get("md5Checksum") or "").lower()
    configured = os.environ.get("A1_RAW_DIR")
    if configured:
        candidate = Path(configured).expanduser().resolve() / SOURCE
        if candidate.is_file() and candidate.stat().st_size == expected_size and expected_md5:
            actual_md5, _ = _hash_file(candidate)
            if actual_md5.lower() == expected_md5:
                return candidate
    api = build_drive_api(read_write=False)
    staged, _ = _download_raw_to_stage(api, item, SOURCE)
    return staged


def _ensure_local_data_plane(api, item: dict[str, Any]) -> Path:
    key = hashlib.sha256(
        (str(item.get("id")) + "|" + str(item.get("md5Checksum")) + "|" + str(item.get("size"))).encode("utf-8")
    ).hexdigest()[:24]
    root = Path.home() / ".a1clean" / "v32_session_phase_probe" / key
    stem = Path(SOURCE).stem
    sem_manifest = root / "00_MANIFESTS" / f"{stem}__SEMANTIC_BUNDLES_MANIFEST.json"
    data_manifest = root / "00_MANIFESTS" / f"{stem}__DATA_PLANE_MANIFEST.json"
    if sem_manifest.is_file() and data_manifest.is_file():
        data = json.loads(data_manifest.read_text(encoding="utf-8"))
        if (
            data.get("status") == "ACCESS_READY_FOR_AI"
            and data.get("source_name") == SOURCE
            and str(data.get("source_drive_id")) == str(item.get("id"))
        ):
            return root
        shutil.rmtree(root, ignore_errors=True)

    root.mkdir(parents=True, exist_ok=True)
    raw = _exact_local_raw(item)
    scratch = root / "_scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    config = DataPlaneConfig(
        engine_root=root,
        raw_dir=raw.parent,
        runtime_ingest_dir=root,
        raw_folder_drive_id=FROZEN_RAW_FOLDER_DRIVE_ID,
        current_folder_drive_id=FROZEN_CURRENT_FOLDER_DRIVE_ID,
        parity_staging_folder_drive_id=FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID,
        run_root=root,
        scratch_dir=scratch,
        generation_id=FROZEN_GENERATION_ID,
        data_plane_impl_version=FROZEN_IMPL_VERSION,
    )
    run_delta(config, _SingleSourceDriveApi(api, dict(item)))
    if not sem_manifest.is_file() or not data_manifest.is_file():
        raise RuntimeError("V32_PHASE_PROBE_DATA_PLANE_BUILD_FAILED")
    return root


def _clock(ts: Any) -> str:
    value = str(ts)
    return value[-8:]


def probe() -> dict[str, Any]:
    api = build_drive_api(read_write=False)
    item = _canonical_raw_items(api)[SOURCE]
    root = _ensure_local_data_plane(api, item)
    stem = Path(SOURCE).stem
    sem_manifest_path = root / "00_MANIFESTS" / f"{stem}__SEMANTIC_BUNDLES_MANIFEST.json"
    rows = json.loads(sem_manifest_path.read_text(encoding="utf-8"))
    matches = [
        x for x in rows
        if str(x.get("ticker")) == TICKER and str(x.get("trading_date")) == TRADING_DATE
    ]
    if len(matches) != 1:
        raise RuntimeError(f"V32_PHASE_PROBE_PACKET_CARDINALITY:{len(matches)}")
    m = matches[0]
    bundle = root / "02_SEMANTIC_BUNDLES" / str(m["bundle_name"])
    lines = bundle.read_text(encoding="utf-8").splitlines()
    idx = int(m["bundle_line_number"]) - 1
    obj = json.loads(lines[idx])
    packet = parse_semantic_packet(obj)
    all_bars, mapping = packet_to_formula_bars(packet)

    keyword_fields = [
        h for h in packet.header
        if any(k in h.upper() for k in ("SESSION", "CLOCK", "CLK_", "MATCH", "AUCTION", "PRE", "POST", "CONTINUOUS", "INDEX"))
    ]

    selected = []
    for raw_row, ts, bar in zip(packet.rows, packet.timestamps, all_bars, strict=True):
        clk = _clock(ts)
        if clk not in TARGET_CLOCKS:
            continue
        selected.append(
            {
                "timestamp": str(ts),
                "clock": clk,
                "raw": dict(raw_row),
                "phase_candidate_fields": {h: raw_row.get(h) for h in keyword_fields},
                "formula_bar": bar,
            }
        )

    return {
        "schema": "A1_V32_SESSION_PHASE_PROBE_V1",
        "status": "PASS",
        "source": SOURCE,
        "source_drive_id": item.get("id"),
        "ticker": TICKER,
        "trading_date": TRADING_DATE,
        "packet_identity": packet.identity.as_dict(),
        "header": list(packet.header),
        "keyword_fields": keyword_fields,
        "formula_field_mapping": mapping,
        "selected_rows": selected,
        "selected_clocks": sorted(x["clock"] for x in selected),
        "packet_row_count": len(packet.rows),
        "all_formula_bar_count": len(all_bars),
        "regular_session_bar_count": sum(1 for b in all_bars if b.get("session_eligible")),
        "nonregular_observation_count": sum(1 for b in all_bars if not b.get("session_eligible")),
        "contract": {
            "read_only_probe": True,
            "phase_not_inferred_from_clock": True,
            "canonical_raw_mutated": False,
            "v31_mutated": False,
        },
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True)
    a = p.parse_args()
    out = probe()
    Path(a.output).write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "schema": out["schema"],
        "status": out["status"],
        "packet_row_count": out["packet_row_count"],
        "regular_session_bar_count": out["regular_session_bar_count"],
        "nonregular_observation_count": out["nonregular_observation_count"],
        "keyword_fields": out["keyword_fields"],
        "selected_clocks": out["selected_clocks"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

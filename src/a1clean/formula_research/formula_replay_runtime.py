from __future__ import annotations

import argparse
import json

from ..google_drive import build_drive_api
from .corpus_translate import _FolderStore
from .formula_replay import replay_source, write_result
from .handbook_candidates import CandidateParams


def _parse_horizons(value: str) -> list[int]:
    rows = [int(item.strip()) for item in value.split(",") if item.strip()]
    if not rows or any(item < 1 for item in rows):
        raise argparse.ArgumentTypeError("horizons must be comma-separated positive integers")
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="a1clean-formula-candidate-replay")
    parser.add_argument("--source-name", required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--software-revision", required=True)
    parser.add_argument("--drive-output-folder-id", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--horizons", type=_parse_horizons, required=True)
    parser.add_argument("--max-packets", type=int, default=0)
    parser.add_argument("--effort-lookback", type=int, required=True)
    parser.add_argument("--progress-lookback", type=int, required=True)
    parser.add_argument("--high-lookback", type=int, required=True)
    parser.add_argument("--recovery-lookback", type=int, required=True)
    parser.add_argument("--low-stabilization-bars", type=int, required=True)
    parser.add_argument("--early-checkpoint-bar", type=int, required=True)
    parser.add_argument("--late-lift-min-bar", type=int, required=True)
    args = parser.parse_args(argv)

    params = CandidateParams(
        effort_lookback=args.effort_lookback,
        progress_lookback=args.progress_lookback,
        high_lookback=args.high_lookback,
        recovery_lookback=args.recovery_lookback,
        low_stabilization_bars=args.low_stabilization_bars,
        early_checkpoint_bar=args.early_checkpoint_bar,
        late_lift_min_bar=args.late_lift_min_bar,
    )
    result = replay_source(
        source_name=args.source_name,
        params=params,
        horizons=args.horizons,
        max_packets=args.max_packets,
    )
    result = {
        **result,
        "request_id": args.request_id,
        "software_revision": args.software_revision,
    }
    write_result(args.output, result)

    writer = build_drive_api(read_write=True)
    store = _FolderStore(writer, args.drive_output_folder_id)
    safe_request = "".join(ch for ch in args.request_id if ch.isalnum() or ch in "-_")
    if not safe_request:
        raise SystemExit("REQUEST_ID_HAS_NO_SAFE_CHARACTERS")
    uploaded = store.upsert_json(
        name=f"CANDIDATE_FORMULA_REPLAY__{safe_request}.json",
        obj=result,
    )
    print(json.dumps({"pass": True, "result": result, "drive_artifact": uploaded}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

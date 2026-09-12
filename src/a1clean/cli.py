from __future__ import annotations

import argparse
import json

from .config import DataPlaneConfig
from .drive_guardrails import run_drive_guardrail_preflight
from .full_shadow_compat import run_full_shadow_parity
from .google_drive import build_drive_api
from .frozen_v2 import run_delta
from .parity import compare_runtime_roots
from .source_parity import run_source_scoped_parity
from .source_preflight import run_source_preflight


def main(argv=None):
    p = argparse.ArgumentParser(prog="a1clean")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("delta", help="Run frozen V2 data-plane against configured staging/current root")
    sub.add_parser(
        "source-preflight",
        help="Compare local read-only RAW files against the canonical Google Drive source universe",
    )
    sub.add_parser(
        "drive-preflight",
        help="Verify governed Drive access separation, including reader write denial and a tiny staging writer create/delete probe",
    )
    sp = sub.add_parser(
        "source-parity",
        help="Run one canonical source through frozen V2 and compare it against the governed Drive baseline as a technical migration gate",
    )
    sp.add_argument("--source-name", required=True)
    sub.add_parser(
        "full-shadow-parity",
        help="Run restart-safe frozen V2 shadow parity across the complete dynamically discovered canonical RAW universe",
    )
    q = sub.add_parser("parity", help="Compare baseline runtime with candidate staging runtime")
    q.add_argument("baseline")
    q.add_argument("candidate")
    args = p.parse_args(argv)

    if args.cmd == "delta":
        cfg = DataPlaneConfig.from_env()
        result = run_delta(cfg, build_drive_api())
        print(
            json.dumps(
                {
                    "semantic_gate": result["semantic_gate"],
                    "delta_counts": {
                        k: len(result["delta"].get(k, []))
                        for k in [
                            "verified_unchanged",
                            "new_processed",
                            "changed_rebuilt",
                            "removed_purged",
                            "holds",
                        ]
                    },
                },
                indent=2,
            )
        )
        return 0 if not result["delta"].get("holds") else 2

    if args.cmd == "source-preflight":
        report = run_source_preflight()
        print(json.dumps(report, indent=2))
        return 0 if report["pass"] else 2

    if args.cmd == "drive-preflight":
        report = run_drive_guardrail_preflight(write_probe=True)
        print(json.dumps(report, indent=2))
        return 0 if report["pass"] else 2

    if args.cmd == "source-parity":
        report = run_source_scoped_parity(args.source_name)
        print(json.dumps(report, indent=2))
        return 0 if report["pass"] else 4

    if args.cmd == "full-shadow-parity":
        report = run_full_shadow_parity()
        print(json.dumps(report, indent=2))
        return 0 if report["pass"] else 5

    report = compare_runtime_roots(args.baseline, args.candidate)
    print(json.dumps(report, indent=2))
    return 0 if report["pass"] else 3


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .config import DataPlaneConfig
from .delta_machine import MACHINE_MODE_CANONICAL, MACHINE_MODE_SHADOW, run_governed_delta_machine
from .drive_guardrails import run_drive_guardrail_preflight
from .full_shadow_compat import run_full_shadow_parity
from .google_drive import build_drive_api
from .frozen_v2 import run_delta
from .parity import compare_runtime_roots
from .pattern_discovery.auto_continue import run_governed_auto_continuation
from .pattern_discovery.runner import run_source_discovery
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
    machine = sub.add_parser(
        "governed-delta",
        help="Run the permanent governed delta-state machine; Gate F uses the same engine under SHADOW commit policy",
    )
    machine.add_argument(
        "--mode",
        type=str.upper,
        choices=[MACHINE_MODE_SHADOW, MACHINE_MODE_CANONICAL],
        default=MACHINE_MODE_SHADOW,
    )
    lane2 = sub.add_parser(
        "pattern-discovery-source",
        help="Run the independent governed algorithmic pattern-discovery machine for one governed source, full trading date, or exact ticker-day scope using an explicit discovery plan",
    )
    lane2.add_argument("--source-name", required=True)
    lane2.add_argument("--plan", required=True, type=Path)
    lane2.add_argument("--packets-per-shard", required=True, type=int)
    lane2.add_argument("--trading-date")
    lane2.add_argument("--ticker")
    lane2.add_argument("--software-revision", default=os.environ.get("GITHUB_SHA", "LOCAL_UNVERSIONED"))
    lane2_auto = sub.add_parser(
        "pattern-discovery-auto-continue",
        help="Continue Lane 2 chronologically from one already verified PASS date; each next date opens only after full persisted PASS/readback of the prior date",
    )
    lane2_auto.add_argument("--source-name", required=True)
    lane2_auto.add_argument("--source-drive-id", required=True)
    lane2_auto.add_argument("--source-sha256", required=True)
    lane2_auto.add_argument("--plan", required=True, type=Path)
    lane2_auto.add_argument("--plan-fingerprint", required=True)
    lane2_auto.add_argument("--packets-per-shard", required=True, type=int)
    lane2_auto.add_argument("--anchor-passed-date", required=True)
    lane2_auto.add_argument("--software-revision", default=os.environ.get("GITHUB_SHA", "LOCAL_UNVERSIONED"))
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

    if args.cmd == "governed-delta":
        report = run_governed_delta_machine(mode=args.mode)
        print(json.dumps(report, indent=2))
        return 0 if report.get("pass") else 6

    if args.cmd == "pattern-discovery-source":
        report = run_source_discovery(
            source_name=args.source_name,
            plan_path=args.plan,
            packets_per_shard=args.packets_per_shard,
            software_revision=args.software_revision,
            trading_date=args.trading_date,
            ticker=args.ticker,
        )
        print(json.dumps(report, indent=2))
        return 0 if report.get("pass") else 7

    if args.cmd == "pattern-discovery-auto-continue":
        report = run_governed_auto_continuation(
            source_name=args.source_name,
            expected_source_drive_id=args.source_drive_id,
            expected_source_sha256=args.source_sha256,
            plan_path=args.plan,
            expected_plan_fingerprint=args.plan_fingerprint,
            packets_per_shard=args.packets_per_shard,
            software_revision=args.software_revision,
            anchor_passed_date=args.anchor_passed_date,
        )
        print(json.dumps(report, indent=2))
        return 0 if report.get("pass") else 8

    report = compare_runtime_roots(args.baseline, args.candidate)
    print(json.dumps(report, indent=2))
    return 0 if report["pass"] else 3


if __name__ == "__main__":
    raise SystemExit(main())

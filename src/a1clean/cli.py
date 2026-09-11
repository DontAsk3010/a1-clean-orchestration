from __future__ import annotations

import argparse
import json
from .config import DataPlaneConfig
from .google_drive import build_drive_api
from .frozen_v2 import run_delta
from .parity import compare_runtime_roots

def main(argv=None):
    p=argparse.ArgumentParser(prog="a1clean")
    sub=p.add_subparsers(dest="cmd",required=True)
    sub.add_parser("delta", help="Run frozen V2 data-plane against configured staging/current root")
    q=sub.add_parser("parity", help="Compare baseline runtime with candidate staging runtime")
    q.add_argument("baseline")
    q.add_argument("candidate")
    args=p.parse_args(argv)
    if args.cmd=="delta":
        cfg=DataPlaneConfig.from_env()
        result=run_delta(cfg,build_drive_api())
        print(json.dumps({"semantic_gate":result["semantic_gate"],"delta_counts":{k:len(result["delta"].get(k,[])) for k in ["verified_unchanged","new_processed","changed_rebuilt","removed_purged","holds"]}},indent=2))
        return 0 if not result["delta"].get("holds") else 2
    report=compare_runtime_roots(args.baseline,args.candidate)
    print(json.dumps(report,indent=2))
    return 0 if report["pass"] else 3

if __name__=="__main__":
    raise SystemExit(main())

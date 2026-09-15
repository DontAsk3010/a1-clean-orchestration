from __future__ import annotations

import argparse
import json
import os

from .corpus_translate_filtered import run_lane2_corpus_translation_filtered


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="a1clean-formula-translation")
    parser.add_argument("--evidence-folder-id", required=True)
    parser.add_argument("--output-folder-id", required=True)
    parser.add_argument("--control-folder-id", required=True)
    parser.add_argument("--audit-folder-id", required=True)
    parser.add_argument("--max-manifests", type=int, default=0)
    parser.add_argument("--software-revision", default=os.environ.get("GITHUB_SHA", "LOCAL_UNVERSIONED"))
    args = parser.parse_args(argv)
    if not args.software_revision or args.software_revision == "LOCAL_UNVERSIONED":
        raise SystemExit("SOFTWARE_REVISION_REQUIRED")
    result = run_lane2_corpus_translation_filtered(
        evidence_folder_id=args.evidence_folder_id,
        output_folder_id=args.output_folder_id,
        control_folder_id=args.control_folder_id,
        audit_folder_id=args.audit_folder_id,
        software_revision=args.software_revision,
        max_manifests=args.max_manifests,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("pass") else 2


if __name__ == "__main__":
    raise SystemExit(main())

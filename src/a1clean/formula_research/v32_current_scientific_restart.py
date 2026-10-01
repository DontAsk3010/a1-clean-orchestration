from __future__ import annotations

"""CURRENT entrypoint for Machine-2 full-depth scientific restart.

V1 and V2 restart artifacts remain historical/audit evidence only for CURRENT
completion. The latest OWNER hard lock materially expands and clarifies the
Machine-2 scientific contract: programmatic processing is allowed, but full
source-supported depth, causal lineage, auditable labels, and all mandatory
Master domains must be represented.

Valid canonical RAW/lossless substrate remains reusable after CURRENT integrity
proof. Affected V2 derived/semantic outputs may not advance the V3 cursor.
"""

from . import v32_current_scientific_restart_engine as _engine
from .m2_full_depth_extension_v2 import augment_scientific_object


PRIOR_LINEAGE = "MACHINE2_CURRENT_FULL_RESTART_FROM_BEGINNING_V2"
LINEAGE = "MACHINE2_CURRENT_FULL_DEPTH_RESTART_FROM_BEGINNING_V3"
CHECKPOINT_SCHEMA = "A1_M2_CURRENT_FULL_DEPTH_CHECKPOINT_V3"
SCIENTIFIC_OBJECT_SCHEMA = "A1_M2_CURRENT_FULL_DEPTH_TICKER_DAY_OBJECT_V3"
DATE_CLOSE_SCHEMA = "A1_M2_CURRENT_FULL_DEPTH_DATE_CLOSE_V3"
CHECKPOINT_NAME = f"{LINEAGE}__CHECKPOINT_CURRENT.json"
CURRENT_STATE_NAME = f"{LINEAGE}__STATE_CURRENT.json"
OWNER_OVERRIDE_EFFECTIVE_DATE = "2026-10-01"
OWNER_FULL_DEPTH_EXTENSION_ACTIVE = True
OWNER_FULL_DEPTH_EXTENSION_VERSION = "V2_EXACT_TIMESTAMP_ALIGNMENT"
OLD_V1_V2_COMPLETION_INHERITED = False

_engine.LINEAGE = LINEAGE
_engine.CHECKPOINT_SCHEMA = CHECKPOINT_SCHEMA
_engine.SCIENTIFIC_OBJECT_SCHEMA = SCIENTIFIC_OBJECT_SCHEMA
_engine.DATE_CLOSE_SCHEMA = DATE_CLOSE_SCHEMA
_engine.CHECKPOINT_NAME = CHECKPOINT_NAME
_engine.CURRENT_STATE_NAME = CURRENT_STATE_NAME

_BASE_BUILD_CURRENT_SCIENTIFIC_OBJECT = _engine.build_current_scientific_object


def build_current_scientific_object(*args, **kwargs):
    obj = _BASE_BUILD_CURRENT_SCIENTIFIC_OBJECT(*args, **kwargs)
    out = augment_scientific_object(obj)
    out["current_full_depth_lineage"] = LINEAGE
    out["old_v1_v2_completion_inherited"] = False
    return out


# run_trading_date resolves the builder from engine-module globals. Bind the
# timestamp-aligned owner-full-depth builder before any persisted V3 unit.
_engine.build_current_scientific_object = build_current_scientific_object

build_continuous_current_enrichment = _engine.build_continuous_current_enrichment
run_trading_date = _engine.run_trading_date
main = _engine.main


def __getattr__(name: str):
    return getattr(_engine, name)


if __name__ == "__main__":
    raise SystemExit(main())

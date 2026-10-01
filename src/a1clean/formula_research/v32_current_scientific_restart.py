from __future__ import annotations

"""Owner-override CURRENT entrypoint for Machine-2 scientific restart.

The pre-2026-10-01 V1 restart artifacts remain historical audit evidence only.
Coverage Matrix revision 8 explicitly requires scientific processing and exact
progressive checkpointing to begin anew under the repaired CURRENT contract.
The implementation engine is retained as the physical/scientific substrate,
then augmented by the latest OWNER hard-lock full-depth layer before any object
is persisted. V1 checkpoint/shards can never move the V2 cursor or be overwritten.
"""

from . import v32_current_scientific_restart_engine as _engine
from .m2_full_depth_extension_v2 import augment_scientific_object


PRIOR_LINEAGE = "MACHINE2_CURRENT_FULL_RESTART_FROM_BEGINNING_V1"
LINEAGE = "MACHINE2_CURRENT_FULL_RESTART_FROM_BEGINNING_V2"
CHECKPOINT_SCHEMA = "A1_M2_CURRENT_SCIENTIFIC_RESTART_CHECKPOINT_V2"
SCIENTIFIC_OBJECT_SCHEMA = "A1_M2_CURRENT_TICKER_DAY_SCIENTIFIC_OBJECT_V2"
DATE_CLOSE_SCHEMA = "A1_M2_CURRENT_DATE_CLOSE_V2"
CHECKPOINT_NAME = f"{LINEAGE}__CHECKPOINT_CURRENT.json"
CURRENT_STATE_NAME = f"{LINEAGE}__STATE_CURRENT.json"
OWNER_OVERRIDE_EFFECTIVE_DATE = "2026-10-01"
OWNER_FULL_DEPTH_EXTENSION_ACTIVE = True
OWNER_FULL_DEPTH_EXTENSION_VERSION = "V2_EXACT_TIMESTAMP_ALIGNMENT"

_engine.LINEAGE = LINEAGE
_engine.CHECKPOINT_SCHEMA = CHECKPOINT_SCHEMA
_engine.SCIENTIFIC_OBJECT_SCHEMA = SCIENTIFIC_OBJECT_SCHEMA
_engine.DATE_CLOSE_SCHEMA = DATE_CLOSE_SCHEMA
_engine.CHECKPOINT_NAME = CHECKPOINT_NAME
_engine.CURRENT_STATE_NAME = CURRENT_STATE_NAME

_BASE_BUILD_CURRENT_SCIENTIFIC_OBJECT = _engine.build_current_scientific_object


def build_current_scientific_object(*args, **kwargs):
    obj = _BASE_BUILD_CURRENT_SCIENTIFIC_OBJECT(*args, **kwargs)
    return augment_scientific_object(obj)


# run_trading_date resolves the builder from the engine module globals, so bind
# the corrected timestamp-aligned full-depth builder before any persisted unit.
_engine.build_current_scientific_object = build_current_scientific_object

build_continuous_current_enrichment = _engine.build_continuous_current_enrichment
run_trading_date = _engine.run_trading_date
main = _engine.main


def __getattr__(name: str):
    return getattr(_engine, name)


if __name__ == "__main__":
    raise SystemExit(main())

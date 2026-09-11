from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

FROZEN_GENERATION_ID = "BEHAVIOR_UNIFORM_COLAB_SEMANTIC_GEN_20260910_01"
FROZEN_IMPL_VERSION = "UNIVERSAL_DELTA_DATA_PLANE_V2_20260911"
FROZEN_RAW_FOLDER_DRIVE_ID = "1gTyt7CzqlubcdZGjWV_lM9Iw8Zg4ib3e"
FROZEN_CURRENT_FOLDER_DRIVE_ID = "1SRN-WWkHJefLGLSN6_SktpVU0Ugjwqc-"
FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID = "1WTb_lGBD6Tuwfcb-1WhsICjyJqzzBtwU"

CANONICAL_RAW_FOLDER_NAME = "02_CURRENT_HISTORICAL_RAW_DATA_UJI"
CANONICAL_CURRENT_FOLDER_NAME = "UNIVERSAL_BEHAVIOR_DATA_PLANE_CURRENT"
PARITY_STAGING_FOLDER_NAME = "UNIVERSAL_BEHAVIOR_DATA_PLANE_PARITY_STAGING"


@dataclass(frozen=True)
class DataPlaneConfig:
    engine_root: Path
    raw_dir: Path
    runtime_ingest_dir: Path
    raw_folder_drive_id: str
    current_folder_drive_id: str
    parity_staging_folder_drive_id: str
    run_root: Path
    scratch_dir: Path
    generation_id: str = FROZEN_GENERATION_ID
    data_plane_impl_version: str = FROZEN_IMPL_VERSION

    @classmethod
    def from_env(cls) -> "DataPlaneConfig":
        raw_dir = Path(os.environ["A1_RAW_DIR"]).expanduser().resolve()
        run_root = Path(os.environ["A1_RUN_ROOT"]).expanduser().resolve()
        scratch = Path(os.environ.get("A1_SCRATCH_DIR", "/tmp/a1-clean")).expanduser().resolve()
        engine_root = Path(os.environ.get("A1_ENGINE_ROOT", str(raw_dir.parent.parent.parent))).expanduser().resolve()
        runtime_ingest_dir = Path(os.environ.get("A1_RUNTIME_INGEST_DIR", str(run_root.parent))).expanduser().resolve()
        scratch.mkdir(parents=True, exist_ok=True)
        return cls(
            engine_root=engine_root,
            raw_dir=raw_dir,
            runtime_ingest_dir=runtime_ingest_dir,
            raw_folder_drive_id=os.environ.get("A1_RAW_FOLDER_DRIVE_ID", FROZEN_RAW_FOLDER_DRIVE_ID),
            current_folder_drive_id=os.environ.get("A1_CURRENT_FOLDER_DRIVE_ID", FROZEN_CURRENT_FOLDER_DRIVE_ID),
            parity_staging_folder_drive_id=os.environ.get(
                "A1_PARITY_STAGING_FOLDER_DRIVE_ID", FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID
            ),
            run_root=run_root,
            scratch_dir=scratch,
        )

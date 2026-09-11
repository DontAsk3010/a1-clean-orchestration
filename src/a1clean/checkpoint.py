from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import json, os

LIFECYCLE = ("DISCOVERED","PROCESSING_STAGING","SOURCE_RECONCILED","COMMIT_READY","COMMITTED")

@dataclass
class RunCheckpoint:
    run_id: str
    authority_revision: str
    repo_commit: str
    generation_id: str
    implementation_version: str
    current_source: str | None = None
    current_stage: str | None = None
    last_validated_source: str | None = None
    last_committed_source: str | None = None
    reconciliation_state: str = "NOT_STARTED"
    hold_reason: str | None = None
    next_exact_resume_point: str | None = None
    updated_at_utc: str | None = None

def atomic_write_checkpoint(path: str | Path, checkpoint: RunCheckpoint) -> None:
    p=Path(path); p.parent.mkdir(parents=True,exist_ok=True)
    checkpoint.updated_at_utc=datetime.now(timezone.utc).isoformat()
    tmp=p.with_suffix(p.suffix+".tmp")
    tmp.write_text(json.dumps(asdict(checkpoint),indent=2,ensure_ascii=False),encoding="utf-8")
    os.replace(tmp,p)

def load_checkpoint(path: str | Path) -> RunCheckpoint | None:
    p=Path(path)
    if not p.exists(): return None
    return RunCheckpoint(**json.loads(p.read_text(encoding="utf-8")))

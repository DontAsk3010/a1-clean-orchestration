"""Integrity-checked loader for the frozen V2 parity anchor."""
from __future__ import annotations
from pathlib import Path
import gzip
import hashlib

_FROZEN_SOURCE_SHA256 = "17ac449b5b04636a2180c3a0c61640fc599230e075314b85988b7e0791b79753"
_source_path = Path(__file__).with_name("_frozen_v2_source.py.gz")
_source_bytes = gzip.decompress(_source_path.read_bytes())
_actual = hashlib.sha256(_source_bytes).hexdigest()
if _actual != _FROZEN_SOURCE_SHA256:
    raise RuntimeError(f"FROZEN_V2_SOURCE_INTEGRITY_MISMATCH: {_actual}")
exec(compile(_source_bytes, "a1clean/_frozen_v2_source.py", "exec"), globals(), globals())
del _source_bytes, _actual

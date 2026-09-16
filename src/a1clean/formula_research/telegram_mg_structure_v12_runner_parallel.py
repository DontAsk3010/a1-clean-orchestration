from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Mapping, Sequence

from . import telegram_mg_structure_v12_runner as core


def _ensure_cache_parallel(sources: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    reused: list[str] = []
    missing: list[Mapping[str, Any]] = []
    for src in sources:
        source = str(src["source_name"])
        if core._meta_ok(source, src):
            reused.append(source)
        else:
            missing.append(src)

    built: list[str] = []
    if missing:
        workers = min(4, len(missing))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(core._build_cache, str(src["source_name"]), src): str(src["source_name"])
                for src in missing
            }
            for fut in as_completed(futures):
                source = futures[fut]
                fut.result()
                built.append(source)

    return {
        "reused_sources": sorted(reused),
        "built_sources": sorted(built),
        "cache_root": str(core._cache_root()),
        "cache_build_parallel_workers": min(4, len(missing)) if missing else 0,
    }


core._ensure_cache = _ensure_cache_parallel


def main() -> int:
    return core.main()


if __name__ == "__main__":
    raise SystemExit(main())

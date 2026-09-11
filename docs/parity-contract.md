# Parity contract

Production automation is disabled until parity passes. The first runner execution writes only to a separate staging runtime root; canonical RAW is read-only and the current governed runtime is not modified.

Required parity evidence includes source identity/SHA, source and routed row counts, unresolved routing, routing/header preservation, ticker-day object counts, physical shard byte hashes, semantic JSONL hashes, market-day indexes, and source status. Runtime timestamps, refresh IDs, and absolute staging path differences are not analytical parity fields.

Start with one complete known source if an isolated-source harness is introduced; do not use row sampling as parity evidence. Then run full 17-source shadow parity against the current baseline.

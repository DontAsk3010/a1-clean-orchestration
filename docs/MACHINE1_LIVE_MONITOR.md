## Machine 1 read-only live monitor

Machine 1 parallel date workers have a dedicated observability path in `.github/workflows/windows-machine1-monitor.yml`. The monitor runs every 10 minutes and can also be dispatched manually. It reads the canonical Machine 1 dispatch registry plus date-scoped checkpoint evidence from `00_CONTROL_AND_CHECKPOINTS` using the read-only Drive credential.

The monitor reconciles both checkpoint styles currently used by Machine 1: mutable `DES2024_YYYYMMDD__CHECKPOINT_CURRENT.json` files and immutable `DES2024_YYYYMMDD__CHECKPOINT_ATOMIC_PASS...json` snapshots. To keep polling lightweight, it downloads only CURRENT files and the highest atomic PASS per date rather than rereading historical atomic snapshots.

Each snapshot exposes, per trading date, worker identity when available, durable progress, latest verified ticker, next exact resume ticker, pull/evidence mode, store/readback state, checkpoint source, and Drive-file heartbeat freshness. `RECENT_WRITE`, `QUIET_NO_RECENT_WRITE`, and `STALE_OBSERVATION_ONLY` are observability states only; they are not semantic authority and do not declare a worker failed.

Outputs are written only to the GitHub Actions run summary and the `machine1-live-monitor` workflow artifact as JSON and Markdown. The monitor never writes canonical RAW, semantic CURRENT, dispatch registry, semantic artifacts, formulas, thresholds, signals, or Telegram logic.

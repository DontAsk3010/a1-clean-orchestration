# Recovery contract

Operational checkpoint lifecycle: `DISCOVERED -> PROCESSING_STAGING -> SOURCE_RECONCILED -> COMMIT_READY -> COMMITTED`.

A checkpoint records run identity, authority revision, repo commit, generation/implementation version, current source/stage, last validated and committed source, reconciliation state, HOLD reason, and `NEXT_EXACT_RESUME_POINT`.

This layer must never change market semantics. Global PASS is promoted only after required source actions and reconciliation complete. Canonical delta concurrency is single-writer and must use `cancel-in-progress: false`.

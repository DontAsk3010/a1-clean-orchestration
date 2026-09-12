# Recovery contract

Recovery state is operational only and must not create analytical logic.

Required lifecycle:

`DISCOVERED -> PROCESSING_STAGING -> SOURCE_RECONCILED -> COMMIT_READY -> COMMITTED`

Persistent checkpoint state and resume evidence belong in Google Drive, not on the owner laptop. The Windows compute-only executor may keep transient scratch/checkpoint material only long enough to safely commit the governed checkpoint back to Drive.

A checkpoint must identify the run/job, authority revision, repository commit, generation/implementation version, source plan, current source/stage, last validated source, last committed source, reconciliation state, HOLD reason if any, and `NEXT_EXACT_RESUME_POINT`.

A terminated runner must resume from the last governed committed checkpoint rather than restart the entire corpus when source-level recovery evidence is valid.

Local scratch loss must not invalidate already committed Drive evidence. Global PASS is forbidden until all required source actions and global reconciliation complete.

# A1 CLEAN automation architecture

- **Drive:** canonical evidence and authority/output plane.
- **GitHub:** source/version/review/workflow control plane.
- **Self-hosted Linux runner:** first execution plane for parity and later delta jobs.
- **Colab:** current lab/bootstrap/manual fallback during migration.
- **Pattern discovery:** separate downstream lane; never a second analytical authority.

The repository contains no canonical RAW, access shards, semantic bundles, credentials, tokens, or trading formula/signal logic.

## Migration rule

`frozen_v2.py` is the parity anchor mechanically derived from the audited notebook. The current generation, implementation version, routing inference constants, shard sizes, delta classifications, and reconciliation behavior are frozen. Environment-specific paths/authentication are injected instead of Colab-specific mounting.

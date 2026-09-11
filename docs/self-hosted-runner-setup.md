# Self-hosted parity runner setup

This is a one-time execution-plane setup. It does not change market methodology.

## Required runner characteristics

- GitHub self-hosted runner registered to this private repository.
- Labels required by the parity workflow: `self-hosted`, `linux`, `x64`, `a1-clean-parity`.
- Python 3.11+.
- Canonical RAW available as a local filesystem path for read access.
- Governed current baseline runtime available as a local filesystem path for comparison.
- A separate writable parity-staging path. Never point staging to `UNIVERSAL_BEHAVIOR_DATA_PLANE_CURRENT`.
- Google Drive **read-only** API credentials available through Application Default Credentials (ADC), only for source identity/discovery parity.
- Scratch directory on local SSD/NVMe where possible.

## Repository variables used by the workflow

- `A1_RAW_DIR` — local canonical RAW mount/path.
- `A1_SCRATCH_DIR` — local temporary scratch path.

`baseline_root` and `staging_root` are supplied explicitly when manually dispatching the parity workflow. No schedule is enabled at this gate.

## Drive authentication

Use an environment-appropriate ADC mechanism. Do not place OAuth tokens, service-account JSON, passwords, or API keys in this repository or workflow YAML. A service account is acceptable only if the canonical Drive folder is explicitly shared to it with the least privilege required. User ADC is also acceptable for a dedicated local runner.

## Fast-fail check

Before a full corpus run:

```bash
python -m a1clean.runner_preflight
```

The preflight validates Python, local RAW/staging separation, staging write access, and read-only Drive API identity access. It reports free disk space as an observation but intentionally does not invent a project threshold.

## Parity sequence

1. Register/configure runner and labels.
2. Set repository variables for local RAW and scratch paths.
3. Ensure baseline runtime is locally readable.
4. Create an empty separate staging root.
5. Run preflight.
6. Manually dispatch `Parity - Manual Self Hosted`.
7. Do not merge/enable canonical automation unless the parity comparator passes.

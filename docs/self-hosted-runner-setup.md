# Self-hosted parity runner setup — Windows-first

This is a one-time execution-plane setup. It does not change market methodology.

## Required runner characteristics

- GitHub self-hosted runner registered to this private repository.
- Primary owner environment: **Windows x64**.
- Labels required by the parity workflow: `self-hosted`, `windows`, `x64`, `a1-clean-parity`.
- Python 3.11+ available from PowerShell/Command Prompt.
- Canonical RAW available as a local Windows filesystem path for read access.
- Governed current baseline runtime available as a local Windows filesystem path for comparison.
- A separate writable parity-staging path. Never point staging to `UNIVERSAL_BEHAVIOR_DATA_PLANE_CURRENT`.
- Google Drive **read-only** API credentials available through Application Default Credentials (ADC), only for source identity/discovery parity.
- Scratch directory on local SSD/NVMe where possible.

## Recommended Windows directory layout

Example only; actual drive/path may differ:

```text
D:\A1_CLEAN\
├── RAW\                  # canonical RAW, read-only during parity
├── BASELINE\             # current governed V2 runtime, read-only
├── PARITY_STAGING\       # runner output only
└── SCRATCH\              # temp SQLite / temporary work
```

## Repository variables used by the workflow

- `A1_RAW_DIR` — local canonical RAW Windows path, for example `D:\A1_CLEAN\RAW`.
- `A1_SCRATCH_DIR` — local temporary scratch Windows path, for example `D:\A1_CLEAN\SCRATCH`.

`baseline_root` and `staging_root` are supplied explicitly when manually dispatching the parity workflow. No schedule is enabled at this gate.

## Drive authentication

Use an environment-appropriate ADC mechanism. Do not place OAuth tokens, service-account JSON, passwords, or API keys in this repository or workflow YAML. A service account is acceptable only if the canonical Drive folder is explicitly shared to it with the least privilege required. User ADC is also acceptable for a dedicated local Windows runner.

## Fast-fail check

From PowerShell in the repository virtual environment:

```powershell
.\.venv\Scripts\python.exe -m a1clean.runner_preflight
```

The preflight validates Python, local RAW/staging separation, staging write access, and read-only Drive API identity access. It reports free disk space as an observation but intentionally does not invent a project threshold.

## Parity sequence

1. Register/configure the Windows x64 self-hosted runner and add label `a1-clean-parity`.
2. Set repository variables for local Windows RAW and scratch paths.
3. Ensure baseline runtime is locally readable.
4. Create an empty separate staging root.
5. Run preflight.
6. Manually dispatch `Parity - Manual Self Hosted`.
7. Do not merge/enable canonical automation unless the parity comparator passes.

Linux is not the default owner environment for this project. It may be evaluated later only as an optional server/cloud execution target if there is a specific operational reason.

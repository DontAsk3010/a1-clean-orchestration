[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Python = 'C:\Users\feri-admin\.a1clean\runtime\python-3.11.9-embed-amd64\python.exe'
$Pip = 'C:\Users\feri-admin\.a1clean\runtime\python-3.11.9-embed-amd64\pip.pyz'
$Site = 'C:\Users\feri-admin\.a1clean\runtime\python-3.11.9-embed-amd64\Lib\site-packages'

function Fail([string]$Code) { throw $Code }
function Require-ExitZero([string]$Code) {
    if ($LASTEXITCODE -ne 0) { Fail "${Code}:$LASTEXITCODE" }
}

if ($env:COMPUTERNAME -ne 'PORSCHE-DESIGN') { Fail "A1_RECOVERY_PREPARE_WRONG_MACHINE:$env:COMPUTERNAME" }
if ($env:RUNNER_NAME -ne 'A1-WINDOWS-COMPUTE-02') { Fail "A1_RECOVERY_PREPARE_WRONG_RUNNER:$env:RUNNER_NAME" }

$blocker = Get-Content -LiteralPath 'canonical-current-recovery-requests\recovery-prepare-blocker-current.json' -Raw -Encoding UTF8 | ConvertFrom-Json
$req = Get-Content -LiteralPath 'canonical-current-recovery-requests\current.json' -Raw -Encoding UTF8 | ConvertFrom-Json
$m2 = Get-Content -LiteralPath 'v32-full-observation-behavior-requests\current.json' -Raw -Encoding UTF8 | ConvertFrom-Json
$auth = Get-Content -LiteralPath 'governance\a1-clean-active-authority-lock.json' -Raw -Encoding UTF8 | ConvertFrom-Json

if ($auth.status -ne 'ACTIVE') { Fail 'A1_RECOVERY_PREPARE_AUTHORITY_NOT_ACTIVE' }
if ($blocker.status -ne 'READY_FOR_GOVERNED_RECOVERY_PREPARE') { Fail "A1_RECOVERY_PREPARE_NOT_ADMITTED:$($blocker.status)" }
if ($req.enabled -ne $true -or [string]$req.mode -ne 'PREPARE_ONLY_NO_CANONICAL_WRITE') { Fail 'A1_RECOVERY_PREPARE_REQUEST_LOCK_FAIL' }
if ($req.canonical_promotion_allowed -ne $false -or $req.raw_write_allowed -ne $false -or $req.heavy_behavior_research_allowed -ne $false) { Fail 'A1_RECOVERY_PREPARE_REQUEST_SAFETY_FAIL' }
if ($m2.enabled -ne $false) { Fail 'A1_RECOVERY_PREPARE_MACHINE2_MUST_REMAIN_DISABLED' }
if ([string]$m2.formula_stage -ne 'CLOSED') { Fail 'A1_RECOVERY_PREPARE_FORMULA_STAGE_MUST_REMAIN_CLOSED' }
if ($m2.canonical_current_recovery_commit_authorized -ne $false) { Fail 'A1_RECOVERY_PREPARE_CANONICAL_COMMIT_MUST_REMAIN_FALSE' }

foreach ($name in @('A1_DRIVE_READER_CREDENTIALS','A1_DRIVE_WRITER_CREDENTIALS')) {
    $p = [Environment]::GetEnvironmentVariable($name,'Process')
    if ([string]::IsNullOrWhiteSpace($p) -or -not (Test-Path -LiteralPath $p -PathType Leaf)) { Fail "A1_RECOVERY_PREPARE_CREDENTIAL_BINDING_FAIL:$name" }
}
$readerHash = (Get-FileHash -LiteralPath $env:A1_DRIVE_READER_CREDENTIALS -Algorithm SHA256).Hash.ToLowerInvariant()
$writerHash = (Get-FileHash -LiteralPath $env:A1_DRIVE_WRITER_CREDENTIALS -Algorithm SHA256).Hash.ToLowerInvariant()
if ($readerHash -eq $writerHash) { Fail 'A1_RECOVERY_PREPARE_READER_WRITER_IDENTICAL_FILE_FORBIDDEN' }
Write-Host 'A1_RECOVERY_PREPARE_ADMISSION=PASS'
Write-Host 'A1_RECOVERY_PREPARE_CREDENTIAL_BINDINGS=PASS_DISTINCT'

& '.\scripts\windows\Ensure-A1PortablePython311.ps1'
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { Fail 'A1_RECOVERY_PREPARE_PORTABLE_PYTHON_MISSING' }
if (-not (Test-Path -LiteralPath $Pip -PathType Leaf)) { Fail 'A1_RECOVERY_PREPARE_PORTABLE_PIP_MISSING' }

& $Python $Pip install --disable-pip-version-check --upgrade --no-deps --target $Site .
Require-ExitZero 'A1_RECOVERY_PREPARE_PROJECT_INSTALL_FAIL'

& $Python -c "import a1clean; print('A1_RECOVERY_PREPARE_PROJECT_IMPORT_PASS')"
Require-ExitZero 'A1_RECOVERY_PREPARE_PROJECT_IMPORT_FAIL'

foreach ($pyFile in @('src\a1clean\canonical_recovery.py','src\a1clean\canonical_recovery_exact_evidence.py')) {
    & $Python -m py_compile $pyFile
    Require-ExitZero "A1_RECOVERY_PREPARE_COMPILE_FAIL:$pyFile"
}
Write-Host 'A1_RECOVERY_PREPARE_COMPILE=PASS'

& $Python -m pytest 'tests\test_canonical_recovery.py' -q
Require-ExitZero 'A1_RECOVERY_PREPARE_TEST_FAIL'
Write-Host 'A1_RECOVERY_PREPARE_UNIT_GATES=PASS'

& $Python -m a1clean.cli source-preflight
Require-ExitZero 'A1_RECOVERY_SOURCE_PREFLIGHT_FAIL'
Write-Host 'A1_RECOVERY_PREPARE_SOURCE_PREFLIGHT=PASS'

$executePy = Join-Path $env:TEMP 'a1_execute_canonical_recovery.py'
@'
import json
from a1clean.canonical_recovery_exact_evidence import run_canonical_current_recovery_prepare_exact_evidence

result = run_canonical_current_recovery_prepare_exact_evidence()
summary = {
    "pass": result.get("pass"),
    "status": result.get("status"),
    "run_folder_id": result.get("run_folder_id"),
    "github_sha": result.get("github_sha"),
    "candidate_folder_id": (result.get("assembly") or {}).get("candidate_folder_id"),
    "candidate_folder_role": (result.get("assembly") or {}).get("candidate_folder_role"),
    "canonical_write_performed": result.get("canonical_write_performed"),
    "raw_write_performed": result.get("raw_write_performed"),
    "promotion_authorized": result.get("promotion_authorized"),
}
print("A1_RECOVERY_RESULT_JSON=" + json.dumps(summary, sort_keys=True, separators=(",", ":")))
raise SystemExit(0 if result.get("pass") is True else 2)
'@ | Set-Content -LiteralPath $executePy -Encoding UTF8

$stdoutPath = Join-Path $env:TEMP 'a1_recovery_stdout.log'
$stderrPath = Join-Path $env:TEMP 'a1_recovery_stderr.log'
Remove-Item -LiteralPath $stdoutPath,$stderrPath -Force -ErrorAction SilentlyContinue
$proc = Start-Process -FilePath $Python -ArgumentList @($executePy) -NoNewWindow -Wait -PassThru -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
$recoveryStdout = if (Test-Path -LiteralPath $stdoutPath -PathType Leaf) { @(Get-Content -LiteralPath $stdoutPath -Encoding UTF8) } else { @() }
$recoveryStderr = if (Test-Path -LiteralPath $stderrPath -PathType Leaf) { @(Get-Content -LiteralPath $stderrPath -Encoding UTF8) } else { @() }
foreach ($line in $recoveryStdout) { Write-Host ([string]$line) }
foreach ($line in $recoveryStderr) { Write-Host ('PYTHON_STDERR|' + [string]$line) }
$recoveryExit = [int]$proc.ExitCode
if ($recoveryExit -ne 0) { Fail "A1_RECOVERY_PREPARE_EXECUTION_FAIL:$recoveryExit" }

$sentinels = @($recoveryStdout | ForEach-Object { [string]$_ } | Where-Object { $_ -like 'A1_RECOVERY_RESULT_JSON=*' })
if ($sentinels.Count -ne 1) { Fail "A1_RECOVERY_PREPARE_RESULT_SENTINEL_CARDINALITY:$($sentinels.Count)" }
$resultJson = $sentinels[0].Substring('A1_RECOVERY_RESULT_JSON='.Length) | ConvertFrom-Json
if ($resultJson.pass -ne $true) { Fail 'A1_RECOVERY_PREPARE_RESULT_PASS_FALSE' }
if ([string]$resultJson.status -ne 'PASS_PREPARED_STAGING_ONLY') { Fail "A1_RECOVERY_PREPARE_RESULT_STATUS:$($resultJson.status)" }
if ([string]::IsNullOrWhiteSpace([string]$resultJson.run_folder_id)) { Fail 'A1_RECOVERY_PREPARE_RESULT_RUN_FOLDER_ID_MISSING' }
if ([string]::IsNullOrWhiteSpace([string]$resultJson.candidate_folder_id)) { Fail 'A1_RECOVERY_PREPARE_RESULT_CANDIDATE_ID_MISSING' }
if ([string]$resultJson.candidate_folder_role -ne 'STAGING_ONLY_NOT_CANONICAL_CURRENT') { Fail 'A1_RECOVERY_PREPARE_RESULT_CANDIDATE_ROLE_MISMATCH' }
if ($resultJson.canonical_write_performed -ne $false -or $resultJson.raw_write_performed -ne $false -or $resultJson.promotion_authorized -ne $false) { Fail 'A1_RECOVERY_PREPARE_RESULT_FORBIDDEN_MUTATION_FLAG' }

Write-Host 'A1_CANONICAL_CURRENT_RECOVERY_PREPARE_STATUS=PASS'
Write-Host "RECOVERY_RUN_FOLDER_ID=$($resultJson.run_folder_id)"
Write-Host "RECOVERY_CANDIDATE_FOLDER_ID=$($resultJson.candidate_folder_id)"
Write-Host "RECOVERY_GITHUB_SHA=$($resultJson.github_sha)"
Write-Host 'TARGET_RUNNER=A1-WINDOWS-COMPUTE-02'
Write-Host 'CANDIDATE_LOCATION=PARITY_STAGING_ONLY'
Write-Host 'RAW_WRITE=false'
Write-Host 'CANONICAL_CURRENT_MUTATION=false'
Write-Host 'HEAVY_BEHAVIOR_RESEARCH=false'
Write-Host 'CANONICAL_PROMOTION_AUTHORIZED=false'

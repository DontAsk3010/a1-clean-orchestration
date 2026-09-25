[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Python = 'C:\Users\feri-admin\.a1clean\runtime\python-3.11.9-embed-amd64\python.exe'
$Pip = 'C:\Users\feri-admin\.a1clean\runtime\python-3.11.9-embed-amd64\pip.pyz'
$Site = 'C:\Users\feri-admin\.a1clean\runtime\python-3.11.9-embed-amd64\Lib\site-packages'

function Fail([string]$Code) { throw $Code }
function Run-Python([string[]]$Args,[string]$FailCode) {
    & $Python @Args
    if ($LASTEXITCODE -ne 0) { Fail "${FailCode}:$LASTEXITCODE" }
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

# Install exactly the current repository revision into the persistent runtime. Dependencies were provisioned separately.
Run-Python @($Pip,'install','--disable-pip-version-check','--upgrade','--no-deps','--target',$Site,'.') 'A1_RECOVERY_PREPARE_PROJECT_INSTALL_FAIL'
Run-Python @('-c',"import a1clean; print('A1_RECOVERY_PREPARE_PROJECT_IMPORT_PASS')") 'A1_RECOVERY_PREPARE_PROJECT_IMPORT_FAIL'

Run-Python @('-m','py_compile','src\a1clean\canonical_recovery.py') 'A1_RECOVERY_PREPARE_COMPILE_FAIL'
Write-Host 'A1_RECOVERY_PREPARE_COMPILE=PASS'

Run-Python @('-m','pytest','tests\test_canonical_recovery.py','-q') 'A1_RECOVERY_PREPARE_TEST_FAIL'
Write-Host 'A1_RECOVERY_PREPARE_UNIT_GATES=PASS'

Run-Python @('-m','a1clean.cli','source-preflight') 'A1_RECOVERY_SOURCE_PREFLIGHT_FAIL'
Write-Host 'A1_RECOVERY_PREPARE_SOURCE_PREFLIGHT=PASS'

Run-Python @('-m','a1clean.canonical_recovery') 'A1_RECOVERY_PREPARE_EXECUTION_FAIL'
Write-Host 'A1_CANONICAL_CURRENT_RECOVERY_PREPARE_STATUS=PASS'
Write-Host 'TARGET_RUNNER=A1-WINDOWS-COMPUTE-02'
Write-Host 'CANDIDATE_LOCATION=PARITY_STAGING_ONLY'
Write-Host 'RAW_WRITE=false'
Write-Host 'CANONICAL_CURRENT_MUTATION=false'
Write-Host 'HEAVY_BEHAVIOR_RESEARCH=false'
Write-Host 'CANONICAL_PROMOTION_AUTHORIZED=false'

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Python = 'C:\Users\feri-admin\.a1clean\runtime\python-3.11.9-embed-amd64\python.exe'
$Pip = 'C:\Users\feri-admin\.a1clean\runtime\python-3.11.9-embed-amd64\pip.pyz'
$Site = 'C:\Users\feri-admin\.a1clean\runtime\python-3.11.9-embed-amd64\Lib\site-packages'
$StepPy = (Resolve-Path 'scripts\windows\recovery_step.py').Path
$PerSourceTimeoutSeconds = 1200
$MaxStepInvocations = 25
$MaxAttemptsPerStep = 2

function Fail([string]$Code) { throw $Code }
function Require-ExitZero([string]$Code) {
    if ($LASTEXITCODE -ne 0) { Fail "${Code}:$LASTEXITCODE" }
}

function Remove-StaleRecoveryTemp {
    $root = $env:RUNNER_TEMP
    if ([string]::IsNullOrWhiteSpace($root) -or -not (Test-Path -LiteralPath $root -PathType Container)) { return }
    Get-ChildItem -LiteralPath $root -Directory -Filter 'a1-governed-delta-source-*' -ErrorAction SilentlyContinue |
        ForEach-Object {
            try { Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction Stop } catch { Write-Host "A1_RECOVERY_TEMP_CLEANUP_WARN=$($_.FullName)" }
        }
}

function Invoke-OneRecoveryStep([int]$Iteration) {
    for ($attempt = 1; $attempt -le $MaxAttemptsPerStep; $attempt++) {
        $stdoutPath = Join-Path $env:TEMP "a1_recovery_step_${Iteration}_${attempt}_stdout.log"
        $stderrPath = Join-Path $env:TEMP "a1_recovery_step_${Iteration}_${attempt}_stderr.log"
        Remove-Item -LiteralPath $stdoutPath,$stderrPath -Force -ErrorAction SilentlyContinue

        Write-Host "A1_RECOVERY_CHUNK_START iteration=$Iteration attempt=$attempt timeout_seconds=$PerSourceTimeoutSeconds"
        $proc = Start-Process -FilePath $Python -ArgumentList @('-u', $StepPy) -NoNewWindow -PassThru -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
        $deadline = (Get-Date).AddSeconds($PerSourceTimeoutSeconds)
        $seenOut = 0
        $seenErr = 0

        while (-not $proc.HasExited -and (Get-Date) -lt $deadline) {
            Start-Sleep -Seconds 5
            $proc.Refresh()
            if (Test-Path -LiteralPath $stdoutPath -PathType Leaf) {
                $lines = @(Get-Content -LiteralPath $stdoutPath -Encoding UTF8)
                if ($lines.Count -gt $seenOut) {
                    for ($i=$seenOut; $i -lt $lines.Count; $i++) { Write-Host ([string]$lines[$i]) }
                    $seenOut = $lines.Count
                }
            }
            if (Test-Path -LiteralPath $stderrPath -PathType Leaf) {
                $lines = @(Get-Content -LiteralPath $stderrPath -Encoding UTF8)
                if ($lines.Count -gt $seenErr) {
                    for ($i=$seenErr; $i -lt $lines.Count; $i++) { Write-Host ('PYTHON_STDERR|' + [string]$lines[$i]) }
                    $seenErr = $lines.Count
                }
            }
        }

        if (-not $proc.HasExited) {
            Write-Host "A1_RECOVERY_SOURCE_TIMEOUT iteration=$Iteration attempt=$attempt"
            try { Stop-Process -Id $proc.Id -Force -ErrorAction Stop } catch { Write-Host "A1_RECOVERY_STOP_WARN=$($_.Exception.Message)" }
            try { Wait-Process -Id $proc.Id -Timeout 30 -ErrorAction SilentlyContinue } catch {}
            Remove-StaleRecoveryTemp
            if ($attempt -lt $MaxAttemptsPerStep) {
                Write-Host "A1_RECOVERY_SOURCE_RETRY iteration=$Iteration next_attempt=$($attempt + 1)"
                continue
            }
            Fail "A1_RECOVERY_SOURCE_TIMEOUT_EXHAUSTED:iteration=$Iteration"
        }

        $proc.Refresh()
        $allOut = if (Test-Path -LiteralPath $stdoutPath -PathType Leaf) { @(Get-Content -LiteralPath $stdoutPath -Encoding UTF8) } else { @() }
        $allErr = if (Test-Path -LiteralPath $stderrPath -PathType Leaf) { @(Get-Content -LiteralPath $stderrPath -Encoding UTF8) } else { @() }
        if ($allOut.Count -gt $seenOut) {
            for ($i=$seenOut; $i -lt $allOut.Count; $i++) { Write-Host ([string]$allOut[$i]) }
        }
        if ($allErr.Count -gt $seenErr) {
            for ($i=$seenErr; $i -lt $allErr.Count; $i++) { Write-Host ('PYTHON_STDERR|' + [string]$allErr[$i]) }
        }

        if ([int]$proc.ExitCode -ne 0) {
            if ($attempt -lt $MaxAttemptsPerStep) {
                Write-Host "A1_RECOVERY_SOURCE_PROCESS_RETRY iteration=$Iteration exit_code=$($proc.ExitCode)"
                Remove-StaleRecoveryTemp
                continue
            }
            Fail "A1_RECOVERY_CHUNK_EXECUTION_FAIL:iteration=$Iteration:exit=$($proc.ExitCode)"
        }

        $sentinels = @($allOut | ForEach-Object { [string]$_ } | Where-Object { $_ -like 'A1_RECOVERY_STEP_JSON=*' })
        if ($sentinels.Count -ne 1) { Fail "A1_RECOVERY_STEP_SENTINEL_CARDINALITY:iteration=$Iteration:count=$($sentinels.Count)" }
        $result = $sentinels[0].Substring('A1_RECOVERY_STEP_JSON='.Length) | ConvertFrom-Json
        if ($result.pass -ne $true) { Fail "A1_RECOVERY_STEP_PASS_FALSE:iteration=$Iteration" }
        return $result
    }
    Fail "A1_RECOVERY_STEP_UNREACHABLE:iteration=$Iteration"
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
Write-Host 'A1_RECOVERY_EXECUTION_MODE=CHECKPOINTED_ONE_SOURCE_PER_PROCESS'
Write-Host "A1_RECOVERY_PER_SOURCE_TIMEOUT_SECONDS=$PerSourceTimeoutSeconds"
Write-Host "A1_RECOVERY_AUTO_RETRY_PER_SOURCE=$MaxAttemptsPerStep"

& '.\scripts\windows\Ensure-A1PortablePython311.ps1'
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { Fail 'A1_RECOVERY_PREPARE_PORTABLE_PYTHON_MISSING' }
if (-not (Test-Path -LiteralPath $Pip -PathType Leaf)) { Fail 'A1_RECOVERY_PREPARE_PORTABLE_PIP_MISSING' }

& $Python $Pip install --disable-pip-version-check --upgrade --no-deps --target $Site .
Require-ExitZero 'A1_RECOVERY_PREPARE_PROJECT_INSTALL_FAIL'
& $Python -c "import a1clean; print('A1_RECOVERY_PREPARE_PROJECT_IMPORT_PASS')"
Require-ExitZero 'A1_RECOVERY_PREPARE_PROJECT_IMPORT_FAIL'

foreach ($pyFile in @('src\a1clean\canonical_recovery.py','src\a1clean\canonical_recovery_exact_evidence.py','scripts\windows\recovery_step.py')) {
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

$finalResult = $null
for ($iteration = 1; $iteration -le $MaxStepInvocations; $iteration++) {
    $stepResult = Invoke-OneRecoveryStep -Iteration $iteration
    $status = [string]$stepResult.status
    Write-Host "A1_RECOVERY_CHUNK_RESULT iteration=$iteration status=$status completed=$($stepResult.completed_source_count) next=$($stepResult.next_exact_resume_source)"

    if ($status -eq 'IN_PROGRESS_CHECKPOINTED') {
        continue
    }
    if ($status -eq 'PASS_PREPARED_STAGING_ONLY') {
        $finalResult = $stepResult
        break
    }
    Fail "A1_RECOVERY_UNEXPECTED_STEP_STATUS:iteration=$iteration:status=$status"
}

if ($null -eq $finalResult) { Fail "A1_RECOVERY_MAX_STEP_INVOCATIONS_EXHAUSTED:$MaxStepInvocations" }
if ([string]::IsNullOrWhiteSpace([string]$finalResult.run_folder_id)) { Fail 'A1_RECOVERY_PREPARE_RESULT_RUN_FOLDER_ID_MISSING' }
if ([string]::IsNullOrWhiteSpace([string]$finalResult.candidate_folder_id)) { Fail 'A1_RECOVERY_PREPARE_RESULT_CANDIDATE_ID_MISSING' }
if ([string]$finalResult.candidate_folder_role -ne 'STAGING_ONLY_NOT_CANONICAL_CURRENT') { Fail 'A1_RECOVERY_PREPARE_RESULT_CANDIDATE_ROLE_MISMATCH' }
if ($finalResult.canonical_write_performed -ne $false -or $finalResult.raw_write_performed -ne $false -or $finalResult.promotion_authorized -ne $false) { Fail 'A1_RECOVERY_PREPARE_RESULT_FORBIDDEN_MUTATION_FLAG' }

Write-Host 'A1_CANONICAL_CURRENT_RECOVERY_PREPARE_STATUS=PASS'
Write-Host "RECOVERY_RUN_FOLDER_ID=$($finalResult.run_folder_id)"
Write-Host "RECOVERY_CANDIDATE_FOLDER_ID=$($finalResult.candidate_folder_id)"
Write-Host "RECOVERY_GITHUB_SHA=$($finalResult.github_sha)"
Write-Host 'TARGET_RUNNER=A1-WINDOWS-COMPUTE-02'
Write-Host 'CANDIDATE_LOCATION=PARITY_STAGING_ONLY'
Write-Host 'RAW_WRITE=false'
Write-Host 'CANONICAL_CURRENT_MUTATION=false'
Write-Host 'HEAVY_BEHAVIOR_RESEARCH=false'
Write-Host 'CANONICAL_PROMOTION_AUTHORIZED=false'

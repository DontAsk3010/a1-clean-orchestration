[CmdletBinding()]
param(
    [string]$VerificationReport = "$HOME\.a1clean\writer-relocation-verification-current.json",
    [string]$InteractiveReport = "$HOME\.a1clean\writer-relocation-interactive-current.json",
    [string]$BindingProof = "$HOME\.a1clean\writer-binding-current.json"
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Get-Sha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

if ($env:COMPUTERNAME -ne 'PORSCHE-DESIGN') {
    throw "A1_BIND_WRONG_MACHINE:$env:COMPUTERNAME"
}
if ([Environment]::UserName -ne 'feri-admin') {
    throw "A1_BIND_WRONG_USER:$([Environment]::UserName)"
}

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'A1_BIND_ADMIN_REQUIRED_FOR_SERVICE_REGISTRY_ENVIRONMENT'
}

if (-not (Test-Path -LiteralPath $VerificationReport -PathType Leaf)) {
    throw "A1_BIND_VERIFICATION_REPORT_MISSING:$VerificationReport"
}
if (-not (Test-Path -LiteralPath $InteractiveReport -PathType Leaf)) {
    throw "A1_BIND_INTERACTIVE_REPORT_MISSING:$InteractiveReport"
}

$v = Get-Content -LiteralPath $VerificationReport -Raw -Encoding UTF8 | ConvertFrom-Json
$i = Get-Content -LiteralPath $InteractiveReport -Raw -Encoding UTF8 | ConvertFrom-Json

if ($v.schema -ne 'A1_DRIVE_WRITER_CANDIDATE_VERIFICATION_V1') {
    throw 'A1_BIND_VERIFICATION_SCHEMA_FAIL'
}
if ($v.status -ne 'PASS_EXACTLY_ONE_LEGITIMATE_EXISTING_WRITER_CANDIDATE') {
    throw "A1_BIND_VERIFICATION_NOT_PASS:$($v.status)"
}
if ([int]$v.verified_legitimate_writer_candidate_count -ne 1) {
    throw 'A1_BIND_VERIFIED_CANDIDATE_COUNT_NOT_ONE'
}
if ($v.binding_changed -ne $false -or $v.drive_write_performed -ne $false -or $v.oauth_reauthorization -ne $false -or $v.canonical_current_mutation -ne $false -or $v.secrets_disclosed -ne $false) {
    throw 'A1_BIND_VERIFICATION_SAFETY_FLAGS_FAIL'
}
if ($i.schema -ne 'A1_DRIVE_WRITER_INTERACTIVE_RELOCATION_SEARCH_V1') {
    throw 'A1_BIND_INTERACTIVE_SCHEMA_FAIL'
}
if ($i.reader_positive_control.detected_by_structural_classifier -ne $true) {
    throw 'A1_BIND_READER_POSITIVE_CONTROL_FAIL'
}

$candidate = [string]$v.verified_candidate_path
$expectedHash = ([string]$v.verified_candidate_sha256).ToLowerInvariant()
if ([string]::IsNullOrWhiteSpace($candidate) -or -not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
    throw 'A1_BIND_VERIFIED_CANDIDATE_FILE_MISSING'
}
$actualHash = Get-Sha256 $candidate
if ($actualHash -ne $expectedHash) {
    throw 'A1_BIND_VERIFIED_CANDIDATE_HASH_DRIFT'
}

$readerPath = [string]$i.reader_positive_control.path
if ([string]::IsNullOrWhiteSpace($readerPath) -or -not (Test-Path -LiteralPath $readerPath -PathType Leaf)) {
    throw 'A1_BIND_READER_FILE_MISSING'
}
$readerHash = Get-Sha256 $readerPath
if ($readerHash -eq $actualHash) {
    throw 'A1_BIND_CANDIDATE_IS_READER'
}

$verifiedRow = @($v.candidates | Where-Object { ([string]$_.path) -eq $candidate -and ([string]$_.sha256).ToLowerInvariant() -eq $actualHash })
if ($verifiedRow.Count -ne 1) {
    throw "A1_BIND_VERIFIED_ROW_CARDINALITY:$($verifiedRow.Count)"
}
$row = $verifiedRow[0]
if ($row.drive_scope_granted_by_tokeninfo -ne $true -or $row.expected_parity_staging_owner_principal -ne $true -or $row.read_only_drive_identity_probe_pass -ne $true) {
    throw 'A1_BIND_VERIFIED_IDENTITY_OR_SCOPE_FAIL'
}
if (([string]$row.principal_email).ToLowerInvariant() -ne 'fjulie8satu@gmail.com') {
    throw 'A1_BIND_PRINCIPAL_EMAIL_FAIL'
}

$services = @(Get-CimInstance Win32_Service -ErrorAction Stop | Where-Object {
    ([string]$_.DisplayName -like '*A1-WINDOWS-COMPUTE-02*') -or
    ([string]$_.PathName -like '*actions-runner-a1-02*')
})
if ($services.Count -ne 1) {
    throw "A1_BIND_MACHINE2_SERVICE_CARDINALITY:$($services.Count)"
}
$svc = $services[0]
$regPath = "HKLM:\SYSTEM\CurrentControlSet\Services\$($svc.Name)"
if (-not (Test-Path -LiteralPath $regPath)) {
    throw 'A1_BIND_MACHINE2_SERVICE_REGISTRY_MISSING'
}

$existing = @()
try {
    $reg = Get-ItemProperty -LiteralPath $regPath -ErrorAction Stop
    if ($null -ne $reg.Environment) { $existing = @($reg.Environment | ForEach-Object { [string]$_ }) }
} catch {}

$preserved = @($existing | Where-Object { $_ -notmatch '^A1_DRIVE_WRITER_CREDENTIALS=' })
$newEnvironment = @($preserved + ("A1_DRIVE_WRITER_CREDENTIALS=" + $candidate))
Set-ItemProperty -LiteralPath $regPath -Name Environment -Value $newEnvironment -Type MultiString

# Exact readback from registry; do not restart service here.
$after = @(Get-ItemProperty -LiteralPath $regPath -Name Environment -ErrorAction Stop).Environment
$writerEntries = @($after | Where-Object { $_ -match '^A1_DRIVE_WRITER_CREDENTIALS=' })
if ($writerEntries.Count -ne 1) {
    throw "A1_BIND_READBACK_ENTRY_CARDINALITY:$($writerEntries.Count)"
}
$boundPath = ([string]$writerEntries[0]).Substring('A1_DRIVE_WRITER_CREDENTIALS='.Length)
if ($boundPath -ne $candidate) {
    throw 'A1_BIND_READBACK_PATH_MISMATCH'
}

$proof = [ordered]@{
    schema = 'A1_DRIVE_WRITER_VERIFIED_BINDING_V1'
    status = 'PASS_BINDING_PERSISTED_SERVICE_RESTART_REQUIRED'
    observed_at_utc = [DateTime]::UtcNow.ToString('o')
    machine = $env:COMPUTERNAME
    interactive_user = [Environment]::UserName
    target_runner = 'A1-WINDOWS-COMPUTE-02'
    service_name = [string]$svc.Name
    service_display_name = [string]$svc.DisplayName
    service_path = [string]$svc.PathName
    service_state_at_binding = [string]$svc.State
    verified_candidate_path = $candidate
    verified_candidate_sha256 = $actualHash
    reader_path = $readerPath
    reader_sha256 = $readerHash
    candidate_is_reader = $false
    principal_email = [string]$row.principal_email
    drive_scope_granted_by_tokeninfo = $true
    registry_binding_readback_pass = $true
    service_restart_performed = $false
    service_restart_required = $true
    drive_write_performed = $false
    oauth_reauthorization = $false
    canonical_current_mutation = $false
    raw_write = $false
    secrets_disclosed = $false
    next_exact_gate = 'CONTROLLED_RESTART_ONLY_A1_WINDOWS_COMPUTE_02_WHEN_IDLE -> DRIVE_GUARDRAIL_PREFLIGHT'
}

$outDir = Split-Path -Parent $BindingProof
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$proof | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $BindingProof -Encoding UTF8

Write-Host 'A1_VERIFIED_WRITER_BINDING_PASS'
Write-Host "SERVICE=$($svc.DisplayName)"
Write-Host "BINDING_PROOF=$BindingProof"
Write-Host 'SERVICE_RESTART_PERFORMED=false'
Write-Host 'SERVICE_RESTART_REQUIRED=true'
Write-Host 'DRIVE_WRITE_PERFORMED=false'
Write-Host 'SECRETS_DISCLOSED=false'

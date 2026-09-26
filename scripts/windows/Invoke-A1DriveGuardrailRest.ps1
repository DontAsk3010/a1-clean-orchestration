[CmdletBinding()]
param(
    [string]$ReportPath = 'C:\Users\feri-admin\.a1clean\drive-guardrail-current.json'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RawId = '1gTyt7CzqlubcdZGjWV_lM9Iw8Zg4ib3e'
$CurrentId = '1SRN-WWkHJefLGLSN6_SktpVU0Ugjwqc-'
$StagingId = '1WTb_lGBD6Tuwfcb-1WhsICjyJqzzBtwU'
$RawName = '02_CURRENT_HISTORICAL_RAW_DATA_UJI'
$CurrentName = 'UNIVERSAL_BEHAVIOR_DATA_PLANE_CURRENT'
$StagingName = 'UNIVERSAL_BEHAVIOR_DATA_PLANE_PARITY_STAGING'
$FolderMime = 'application/vnd.google-apps.folder'
$ReadOnlyScope = 'https://www.googleapis.com/auth/drive.readonly'
$ReadWriteScope = 'https://www.googleapis.com/auth/drive'
$RecoveryRequestPath = 'canonical-current-recovery-requests\current.json'

function Fail([string]$Code) { throw $Code }
function UrlEncode([string]$Value) { [Uri]::EscapeDataString($Value) }

if ($env:COMPUTERNAME -ne 'PORSCHE-DESIGN') { Fail "A1_DRIVE_GUARDRAIL_WRONG_MACHINE:$env:COMPUTERNAME" }
if ($env:RUNNER_NAME -ne 'A1-WINDOWS-COMPUTE-02') { Fail "A1_DRIVE_GUARDRAIL_WRONG_RUNNER:$env:RUNNER_NAME" }
if (-not (Test-Path -LiteralPath $RecoveryRequestPath -PathType Leaf)) { Fail 'A1_DRIVE_GUARDRAIL_RECOVERY_REQUEST_MISSING' }
$recoveryRequest = Get-Content -LiteralPath $RecoveryRequestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]$recoveryRequest.schema -ne 'A1_CANONICAL_CURRENT_RECOVERY_REQUEST_V1') { Fail 'A1_DRIVE_GUARDRAIL_RECOVERY_REQUEST_SCHEMA_FAIL' }
if ($recoveryRequest.enabled -ne $true) { Fail 'A1_DRIVE_GUARDRAIL_RECOVERY_REQUEST_NOT_ENABLED' }
if ([string]$recoveryRequest.mode -ne 'PREPARE_ONLY_NO_CANONICAL_WRITE') { Fail 'A1_DRIVE_GUARDRAIL_RECOVERY_REQUEST_MODE_FAIL' }
if ([string]$recoveryRequest.expected_missing_current_folder_id -ne $CurrentId) { Fail 'A1_DRIVE_GUARDRAIL_RECOVERY_CURRENT_ID_MISMATCH' }
if ([string]$recoveryRequest.expected_missing_current_folder_name -ne $CurrentName) { Fail 'A1_DRIVE_GUARDRAIL_RECOVERY_CURRENT_NAME_MISMATCH' }
if ([string]$recoveryRequest.parity_staging_folder_id -ne $StagingId) { Fail 'A1_DRIVE_GUARDRAIL_RECOVERY_STAGING_ID_MISMATCH' }
if ($recoveryRequest.canonical_promotion_allowed -ne $false -or $recoveryRequest.raw_write_allowed -ne $false -or $recoveryRequest.heavy_behavior_research_allowed -ne $false) { Fail 'A1_DRIVE_GUARDRAIL_RECOVERY_SAFETY_LOCK_FAIL' }

$readerPath = [string]$env:A1_DRIVE_READER_CREDENTIALS
$writerPath = [string]$env:A1_DRIVE_WRITER_CREDENTIALS
if ([string]::IsNullOrWhiteSpace($readerPath) -or -not (Test-Path -LiteralPath $readerPath -PathType Leaf)) { Fail 'A1_DRIVE_GUARDRAIL_READER_CREDENTIAL_MISSING' }
if ([string]::IsNullOrWhiteSpace($writerPath) -or -not (Test-Path -LiteralPath $writerPath -PathType Leaf)) { Fail 'A1_DRIVE_GUARDRAIL_WRITER_CREDENTIAL_MISSING' }
$readerHash = (Get-FileHash -LiteralPath $readerPath -Algorithm SHA256).Hash.ToLowerInvariant()
$writerHash = (Get-FileHash -LiteralPath $writerPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($readerHash -eq $writerHash) { Fail 'A1_DRIVE_GUARDRAIL_READER_WRITER_IDENTICAL_FILE_FORBIDDEN' }

function Get-AuthorizedUserAccessToken([string]$Path, [string]$ExpectedScope, [string]$Role) {
    $c = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$c.type -ne 'authorized_user') { Fail "A1_DRIVE_GUARDRAIL_${Role}_UNSUPPORTED_CREDENTIAL_TYPE" }
    foreach ($name in @('client_id','client_secret','refresh_token')) {
        if (-not ($c.PSObject.Properties.Name -contains $name) -or [string]::IsNullOrWhiteSpace([string]$c.$name)) { Fail "A1_DRIVE_GUARDRAIL_${Role}_MISSING_$name" }
    }
    $tokenUri = if (($c.PSObject.Properties.Name -contains 'token_uri') -and -not [string]::IsNullOrWhiteSpace([string]$c.token_uri)) { [string]$c.token_uri } else { 'https://oauth2.googleapis.com/token' }
    if ($tokenUri -notmatch '^https://oauth2\.googleapis\.com/token$|^https://accounts\.google\.com/o/oauth2/token$') { Fail "A1_DRIVE_GUARDRAIL_${Role}_UNEXPECTED_TOKEN_URI" }
    $token = Invoke-RestMethod -Method Post -Uri $tokenUri -ContentType 'application/x-www-form-urlencoded' -Body @{
        client_id = [string]$c.client_id
        client_secret = [string]$c.client_secret
        refresh_token = [string]$c.refresh_token
        grant_type = 'refresh_token'
    }
    $access = [string]$token.access_token
    if ([string]::IsNullOrWhiteSpace($access)) { Fail "A1_DRIVE_GUARDRAIL_${Role}_REFRESH_NO_ACCESS_TOKEN" }
    $info = Invoke-RestMethod -Method Get -Uri ('https://oauth2.googleapis.com/tokeninfo?access_token=' + (UrlEncode $access))
    $scopes = @(([string]$info.scope) -split '\s+' | Where-Object { $_ })
    if ($scopes -notcontains $ExpectedScope) { Fail "A1_DRIVE_GUARDRAIL_${Role}_EXPECTED_SCOPE_NOT_GRANTED" }
    return [pscustomobject]@{ AccessToken = $access; Scopes = $scopes }
}

$reader = Get-AuthorizedUserAccessToken -Path $readerPath -ExpectedScope $ReadOnlyScope -Role 'READER'
$writer = Get-AuthorizedUserAccessToken -Path $writerPath -ExpectedScope $ReadWriteScope -Role 'WRITER'
$readerHeaders = @{ Authorization = 'Bearer ' + $reader.AccessToken }
$writerHeaders = @{ Authorization = 'Bearer ' + $writer.AccessToken }
$folderFields = 'id,name,mimeType,parents,capabilities(canAddChildren,canDelete,canEdit,canTrashChildren)'

function Get-FolderSnapshot([string]$Id, [hashtable]$Headers, [string]$Role) {
    $uri = 'https://www.googleapis.com/drive/v3/files/' + $Id + '?fields=' + (UrlEncode $folderFields) + '&supportsAllDrives=true'
    try { return Invoke-RestMethod -Method Get -Uri $uri -Headers $Headers }
    catch {
        $status = $null
        try { $status = [int]$_.Exception.Response.StatusCode } catch {}
        Fail "A1_DRIVE_GUARDRAIL_${Role}_FOLDER_READ_FAIL:id=${Id}:http=$status"
    }
}

$raw = Get-FolderSnapshot -Id $RawId -Headers $readerHeaders -Role 'RAW_READER'
$staging = Get-FolderSnapshot -Id $StagingId -Headers $writerHeaders -Role 'STAGING_WRITER'
$currentState = $null
$currentHttp = $null
$currentUnexpected = $null
$currentUri = 'https://www.googleapis.com/drive/v3/files/' + $CurrentId + '?fields=' + (UrlEncode 'id,name,mimeType,trashed,parents') + '&supportsAllDrives=true'
try {
    $currentUnexpected = Invoke-RestMethod -Method Get -Uri $currentUri -Headers $readerHeaders
    $currentState = 'UNEXPECTEDLY_PRESENT'
} catch {
    try { $currentHttp = [int]$_.Exception.Response.StatusCode } catch {}
    if ($currentHttp -eq 404) { $currentState = 'NOT_FOUND_404_EXPECTED_FOR_RECOVERY' }
    else { Fail "A1_DRIVE_GUARDRAIL_CURRENT_READER_UNEXPECTED_ERROR:http=$currentHttp" }
}
if ($currentState -ne 'NOT_FOUND_404_EXPECTED_FOR_RECOVERY') {
    $name = if ($null -ne $currentUnexpected) { [string]$currentUnexpected.name } else { '' }
    Fail "A1_DRIVE_GUARDRAIL_RECOVERY_EXPECTED_CURRENT_MISSING_BUT_PRESENT:name=$name"
}

$rawIdentity = ([string]$raw.id -eq $RawId -and [string]$raw.name -eq $RawName -and [string]$raw.mimeType -eq $FolderMime)
$stagingIdentity = ([string]$staging.id -eq $StagingId -and [string]$staging.name -eq $StagingName -and [string]$staging.mimeType -eq $FolderMime)
$rawStagingDistinct = ([string]$raw.id -ne [string]$staging.id)
$stagingCanAdd = [bool]$staging.capabilities.canAddChildren
if (-not ($rawIdentity -and $stagingIdentity -and $rawStagingDistinct -and $stagingCanAdd)) { Fail 'A1_DRIVE_GUARDRAIL_RECOVERY_FOLDER_SEPARATION_OR_IDENTITY_FAIL' }

function New-ProbeFile([hashtable]$Headers, [string]$FolderId, [string]$Name) {
    $boundary = 'a1_' + [Guid]::NewGuid().ToString('N')
    $metadata = @{ name = $Name; parents = @($FolderId) } | ConvertTo-Json -Compress
    $payload = "--$boundary`r`nContent-Type: application/json; charset=UTF-8`r`n`r`n$metadata`r`n--$boundary`r`nContent-Type: text/plain; charset=UTF-8`r`n`r`nA1 CLEAN parity staging guardrail probe. Safe to delete.`r`n--$boundary--`r`n"
    $bytes = [Text.Encoding]::UTF8.GetBytes($payload)
    $uri = 'https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,name,parents&supportsAllDrives=true'
    return Invoke-RestMethod -Method Post -Uri $uri -Headers $Headers -ContentType ("multipart/related; boundary=$boundary") -Body $bytes
}

function Remove-ProbeFile([hashtable]$Headers, [string]$Id) {
    $uri = 'https://www.googleapis.com/drive/v3/files/' + $Id + '?supportsAllDrives=true'
    Invoke-RestMethod -Method Delete -Uri $uri -Headers $Headers | Out-Null
}

$stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
$readerProbe = [ordered]@{ pass = $false; write_denied = $false; http_status = $null; cleanup = 'NOT_CREATED' }
$readerCreatedId = $null
try {
    $created = New-ProbeFile -Headers $readerHeaders -FolderId $StagingId -Name ("A1_READER_WRITE_DENIAL_PROBE_$stamp.txt")
    $readerCreatedId = [string]$created.id
    if ($readerCreatedId) {
        try { Remove-ProbeFile -Headers $writerHeaders -Id $readerCreatedId; $readerProbe.cleanup = 'DELETED_BY_WRITER_AFTER_UNEXPECTED_READER_WRITE' } catch { $readerProbe.cleanup = 'CLEANUP_FAILED' }
    }
} catch {
    $status = $null
    try { $status = [int]$_.Exception.Response.StatusCode } catch {}
    $readerProbe.http_status = $status
    if ($status -in @(401,403)) { $readerProbe.pass = $true; $readerProbe.write_denied = $true }
    else { Fail "A1_DRIVE_GUARDRAIL_READER_WRITE_DENIAL_PROBE_FAIL:http=$status" }
}
if (-not $readerProbe.pass) { Fail 'A1_DRIVE_GUARDRAIL_READER_WRITE_UNEXPECTEDLY_SUCCEEDED' }

$writerProbe = [ordered]@{ pass = $false; cleanup = 'NOT_CREATED'; created_parent_ok = $false }
$writerCreatedId = $null
try {
    $created = New-ProbeFile -Headers $writerHeaders -FolderId $StagingId -Name ("A1_PARITY_STAGING_WRITE_PROBE_$stamp.txt")
    $writerCreatedId = [string]$created.id
    $parentOk = $StagingId -in @($created.parents)
    if ([string]::IsNullOrWhiteSpace($writerCreatedId) -or -not $parentOk) { Fail 'A1_DRIVE_GUARDRAIL_WRITER_PROBE_PARENT_RECONCILIATION_FAIL' }
    $writerProbe.created_parent_ok = $true
    Remove-ProbeFile -Headers $writerHeaders -Id $writerCreatedId
    $writerProbe.cleanup = 'DELETED'
    $writerProbe.pass = $true
} catch {
    if ($writerCreatedId) {
        try { Remove-ProbeFile -Headers $writerHeaders -Id $writerCreatedId; $writerProbe.cleanup = 'DELETED_AFTER_ERROR' } catch { $writerProbe.cleanup = 'CLEANUP_FAILED' }
    }
    throw
}

$report = [ordered]@{
    schema = 'A1_DRIVE_GUARDRAIL_RECOVERY_PREREQUISITE_V1'
    status = 'PASS_RECOVERY_PREREQUISITE_EXPECTED_CURRENT_404'
    pass = $true
    observed_at_utc = [DateTime]::UtcNow.ToString('o')
    machine = $env:COMPUTERNAME
    runner = $env:RUNNER_NAME
    recovery_request_mode = [string]$recoveryRequest.mode
    credential_channels = [ordered]@{ raw_and_current = 'READER_CREDENTIAL / DRIVE_READONLY_SCOPE'; parity_staging = 'WRITER_CREDENTIAL / DRIVE_WRITE_SCOPE' }
    checks = [ordered]@{
        raw_identity = $true
        current_expected_missing_404 = $true
        staging_identity = $true
        raw_staging_ids_distinct = $true
        staging_writer_has_write_capability = $true
        reader_write_denial_probe_in_staging = $readerProbe
        staging_writer_create_delete_probe = $writerProbe
    }
    folders = [ordered]@{
        raw_via_reader = [ordered]@{ id = [string]$raw.id; name = [string]$raw.name; mimeType = [string]$raw.mimeType; capabilities = $raw.capabilities }
        current_via_reader = [ordered]@{ id = $CurrentId; expected_name = $CurrentName; state = $currentState; http_status = $currentHttp }
        staging_via_writer = [ordered]@{ id = [string]$staging.id; name = [string]$staging.name; mimeType = [string]$staging.mimeType; capabilities = $staging.capabilities }
    }
    reader_sha256 = $readerHash
    writer_sha256 = $writerHash
    reader_writer_distinct = $true
    raw_write_performed = $false
    current_write_performed = $false
    staging_only_write_probe = $true
    canonical_current_mutation = $false
    secrets_disclosed = $false
    next_exact_gate = 'CANONICAL_CURRENT_RECOVERY_PREPARE_IN_PARITY_STAGING_ONLY'
}
$dir = Split-Path -Parent $ReportPath
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$report | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $ReportPath -Encoding UTF8

Write-Host 'A1_DRIVE_GUARDRAIL_RECOVERY_STATUS=PASS_RECOVERY_PREREQUISITE_EXPECTED_CURRENT_404'
Write-Host 'RAW_READER_IDENTITY=PASS'
Write-Host 'CURRENT_EXPECTED_MISSING_404=PASS'
Write-Host 'STAGING_WRITER_IDENTITY=PASS'
Write-Host 'READER_WRITE_DENIAL_IN_STAGING=PASS'
Write-Host 'WRITER_CREATE_DELETE_IN_STAGING=PASS'
Write-Host 'RAW_WRITE_PERFORMED=false'
Write-Host 'CURRENT_WRITE_PERFORMED=false'
Write-Host 'CANONICAL_CURRENT_MUTATION=false'
Write-Host 'SECRETS_DISCLOSED=false'
Write-Host "REPORT_PATH=$ReportPath"

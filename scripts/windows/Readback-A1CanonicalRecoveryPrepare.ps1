[CmdletBinding()]
param(
    [string]$ExpectedRecoverySha = 'f621ccdc78dee31069a76cecfff26af80ef1681f',
    [string]$ReportPath = 'C:\Users\feri-admin\.a1clean\recovery-readback-current.json'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$StagingId = '1WTb_lGBD6Tuwfcb-1WhsICjyJqzzBtwU'
$CurrentId = '1SRN-WWkHJefLGLSN6_SktpVU0Ugjwqc-'
$FolderMime = 'application/vnd.google-apps.folder'
$ReadOnlyScope = 'https://www.googleapis.com/auth/drive.readonly'
$ReadWriteScope = 'https://www.googleapis.com/auth/drive'
$ExpectedLogical = @('00_MANIFESTS','01_ACCESS_SHARDS','02_SEMANTIC_BUNDLES','03_MARKET_DAY_INDEX','04_SEMANTIC_EVENT_CONTRACT')

function Fail([string]$Code) { throw $Code }
function UrlEncode([string]$Value) { [Uri]::EscapeDataString($Value) }

if ($env:COMPUTERNAME -ne 'PORSCHE-DESIGN') { Fail "A1_RECOVERY_READBACK_WRONG_MACHINE:$env:COMPUTERNAME" }
if ($env:RUNNER_NAME -ne 'A1-WINDOWS-COMPUTE-02') { Fail "A1_RECOVERY_READBACK_WRONG_RUNNER:$env:RUNNER_NAME" }

$readerPath = [string]$env:A1_DRIVE_READER_CREDENTIALS
$writerPath = [string]$env:A1_DRIVE_WRITER_CREDENTIALS
if ([string]::IsNullOrWhiteSpace($readerPath) -or -not (Test-Path -LiteralPath $readerPath -PathType Leaf)) { Fail 'A1_RECOVERY_READBACK_READER_CREDENTIAL_MISSING' }
if ([string]::IsNullOrWhiteSpace($writerPath) -or -not (Test-Path -LiteralPath $writerPath -PathType Leaf)) { Fail 'A1_RECOVERY_READBACK_WRITER_CREDENTIAL_MISSING' }
$readerHash = (Get-FileHash -LiteralPath $readerPath -Algorithm SHA256).Hash.ToLowerInvariant()
$writerHash = (Get-FileHash -LiteralPath $writerPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($readerHash -eq $writerHash) { Fail 'A1_RECOVERY_READBACK_READER_WRITER_IDENTICAL_FORBIDDEN' }

function Get-AccessToken([string]$Path, [string]$ExpectedScope, [string]$Role) {
    $c = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$c.type -ne 'authorized_user') { Fail "A1_RECOVERY_READBACK_${Role}_UNSUPPORTED_CREDENTIAL_TYPE" }
    foreach ($name in @('client_id','client_secret','refresh_token')) {
        if (-not ($c.PSObject.Properties.Name -contains $name) -or [string]::IsNullOrWhiteSpace([string]$c.$name)) {
            Fail "A1_RECOVERY_READBACK_${Role}_MISSING_$name"
        }
    }
    $tokenUri = if (($c.PSObject.Properties.Name -contains 'token_uri') -and -not [string]::IsNullOrWhiteSpace([string]$c.token_uri)) { [string]$c.token_uri } else { 'https://oauth2.googleapis.com/token' }
    $token = Invoke-RestMethod -Method Post -Uri $tokenUri -ContentType 'application/x-www-form-urlencoded' -Body @{
        client_id = [string]$c.client_id
        client_secret = [string]$c.client_secret
        refresh_token = [string]$c.refresh_token
        grant_type = 'refresh_token'
    }
    $access = [string]$token.access_token
    if ([string]::IsNullOrWhiteSpace($access)) { Fail "A1_RECOVERY_READBACK_${Role}_REFRESH_NO_ACCESS_TOKEN" }
    $info = Invoke-RestMethod -Method Get -Uri ('https://oauth2.googleapis.com/tokeninfo?access_token=' + (UrlEncode $access))
    $scopes = @(([string]$info.scope) -split '\s+' | Where-Object { $_ })
    if ($scopes -notcontains $ExpectedScope) { Fail "A1_RECOVERY_READBACK_${Role}_EXPECTED_SCOPE_NOT_GRANTED" }
    return $access
}

$readerToken = Get-AccessToken -Path $readerPath -ExpectedScope $ReadOnlyScope -Role 'READER'
$writerToken = Get-AccessToken -Path $writerPath -ExpectedScope $ReadWriteScope -Role 'WRITER'
$readerHeaders = @{ Authorization = 'Bearer ' + $readerToken }
$writerHeaders = @{ Authorization = 'Bearer ' + $writerToken }

function Get-Children([string]$ParentId, [hashtable]$Headers) {
    $all = New-Object System.Collections.Generic.List[object]
    $page = $null
    do {
        $q = "'$ParentId' in parents and trashed=false"
        $uri = 'https://www.googleapis.com/drive/v3/files?q=' + (UrlEncode $q) + '&pageSize=1000&supportsAllDrives=true&includeItemsFromAllDrives=true&fields=' + (UrlEncode 'nextPageToken,files(id,name,mimeType,parents,size,md5Checksum)')
        if ($page) { $uri += '&pageToken=' + (UrlEncode $page) }
        $res = Invoke-RestMethod -Method Get -Uri $uri -Headers $Headers
        foreach ($item in @($res.files)) { [void]$all.Add($item) }
        $page = if ($res.PSObject.Properties.Name -contains 'nextPageToken') { [string]$res.nextPageToken } else { $null }
    } while (-not [string]::IsNullOrWhiteSpace($page))
    return @($all)
}

function Get-FileJson([string]$FileId, [hashtable]$Headers) {
    $uri = 'https://www.googleapis.com/drive/v3/files/' + $FileId + '?alt=media&supportsAllDrives=true'
    return Invoke-RestMethod -Method Get -Uri $uri -Headers $Headers
}

function Get-Meta([string]$FileId, [hashtable]$Headers) {
    $fields = 'id,name,mimeType,parents,trashed'
    $uri = 'https://www.googleapis.com/drive/v3/files/' + $FileId + '?fields=' + (UrlEncode $fields) + '&supportsAllDrives=true'
    return Invoke-RestMethod -Method Get -Uri $uri -Headers $Headers
}

function Get-NamesFingerprint([object[]]$Items) {
    $names = @($Items | ForEach-Object { [string]$_.name } | Sort-Object)
    $json = ConvertTo-Json -Compress -InputObject @($names)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($json)
        return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-','').ToLowerInvariant()
    } finally { $sha.Dispose() }
}

$currentMissing404 = $false
try {
    [void](Get-Meta -FileId $CurrentId -Headers $readerHeaders)
} catch {
    $status = $null
    try { $status = [int]$_.Exception.Response.StatusCode } catch {}
    if ($status -eq 404) { $currentMissing404 = $true } else { Fail "A1_RECOVERY_READBACK_CURRENT_CHECK_FAIL:http=$status" }
}
if (-not $currentMissing404) { Fail 'A1_RECOVERY_READBACK_CURRENT_UNEXPECTEDLY_EXISTS' }

$staging = Get-Meta -FileId $StagingId -Headers $writerHeaders
if ([string]$staging.mimeType -ne $FolderMime) { Fail 'A1_RECOVERY_READBACK_STAGING_NOT_FOLDER' }

$rootChildren = Get-Children -ParentId $StagingId -Headers $writerHeaders
$runFolders = @($rootChildren | Where-Object { [string]$_.mimeType -eq $FolderMime -and [string]$_.name -like 'CANONICAL_CURRENT_RECOVERY_PREPARE_*' })
$matches = New-Object System.Collections.Generic.List[object]
foreach ($run in $runFolders) {
    $children = Get-Children -ParentId ([string]$run.id) -Headers $writerHeaders
    $finalItems = @($children | Where-Object { [string]$_.mimeType -ne $FolderMime -and [string]$_.name -eq 'RECOVERY_PREPARE_FINAL.json' })
    if ($finalItems.Count -gt 1) { Fail "A1_RECOVERY_READBACK_DUPLICATE_FINAL_REPORT:$($run.id)" }
    if ($finalItems.Count -eq 1) {
        $final = Get-FileJson -FileId ([string]$finalItems[0].id) -Headers $writerHeaders
        if ([string]$final.github_sha -eq $ExpectedRecoverySha) {
            [void]$matches.Add([pscustomobject]@{ Run = $run; Children = $children; FinalItem = $finalItems[0]; Final = $final })
        }
    }
}
if ($matches.Count -ne 1) { Fail "A1_RECOVERY_READBACK_EXPECTED_ONE_PASS_RUN:observed=$($matches.Count)" }

$m = $matches[0]
$final = $m.Final
$runId = [string]$m.Run.id
if ([string]$final.schema -ne 'A1_CANONICAL_CURRENT_RECOVERY_PREPARE_RESULT_V1') { Fail 'A1_RECOVERY_READBACK_FINAL_SCHEMA_MISMATCH' }
if ($final.pass -ne $true) { Fail 'A1_RECOVERY_READBACK_FINAL_PASS_FALSE' }
if ([string]$final.status -ne 'PASS_PREPARED_STAGING_ONLY') { Fail 'A1_RECOVERY_READBACK_FINAL_STATUS_MISMATCH' }
if ([string]$final.mode -ne 'PREPARE_ONLY_NO_CANONICAL_WRITE') { Fail 'A1_RECOVERY_READBACK_MODE_MISMATCH' }
if ([string]$final.run_folder_id -ne $runId) { Fail 'A1_RECOVERY_READBACK_RUN_FOLDER_ID_MISMATCH' }
if ([string]$final.canonical_current_expected_old_id -ne $CurrentId) { Fail 'A1_RECOVERY_READBACK_OLD_CURRENT_ID_MISMATCH' }
if ($final.canonical_write_performed -ne $false -or $final.raw_write_performed -ne $false -or $final.promotion_authorized -ne $false) { Fail 'A1_RECOVERY_READBACK_FORBIDDEN_MUTATION_FLAG' }
if ([string]$final.missing_current_reader.state -ne 'NOT_FOUND_404' -or [string]$final.missing_current_writer.state -ne 'NOT_FOUND_404') { Fail 'A1_RECOVERY_READBACK_MISSING_CURRENT_PROOF_MISMATCH' }

$assembly = $final.assembly
if ($null -eq $assembly -or $assembly.pass -ne $true) { Fail 'A1_RECOVERY_READBACK_ASSEMBLY_NOT_PASS' }
if ([string]$assembly.candidate_folder_role -ne 'STAGING_ONLY_NOT_CANONICAL_CURRENT') { Fail 'A1_RECOVERY_READBACK_CANDIDATE_ROLE_MISMATCH' }
$candidateId = [string]$assembly.candidate_folder_id
if ([string]::IsNullOrWhiteSpace($candidateId)) { Fail 'A1_RECOVERY_READBACK_CANDIDATE_ID_MISSING' }
$candidateMeta = Get-Meta -FileId $candidateId -Headers $writerHeaders
if ([string]$candidateMeta.mimeType -ne $FolderMime -or $runId -notin @($candidateMeta.parents)) { Fail 'A1_RECOVERY_READBACK_CANDIDATE_PARENT_MISMATCH' }

$candidateChildren = Get-Children -ParentId $candidateId -Headers $writerHeaders
$logicalFolders = @($candidateChildren | Where-Object { [string]$_.mimeType -eq $FolderMime })
$logicalNames = @($logicalFolders | ForEach-Object { [string]$_.name } | Sort-Object)
if ($logicalFolders.Count -ne $ExpectedLogical.Count) { Fail "A1_RECOVERY_READBACK_LOGICAL_FOLDER_COUNT_MISMATCH:$($logicalFolders.Count)" }
if ((@($logicalNames) -join '|') -ne (@($ExpectedLogical | Sort-Object) -join '|')) { Fail 'A1_RECOVERY_READBACK_LOGICAL_FOLDER_NAMES_MISMATCH' }

$liveLogical = [ordered]@{}
foreach ($name in $ExpectedLogical) {
    $rows = @($logicalFolders | Where-Object { [string]$_.name -eq $name })
    if ($rows.Count -ne 1) { Fail "A1_RECOVERY_READBACK_LOGICAL_CARDINALITY:${name}:$($rows.Count)" }
    $folderId = [string]$rows[0].id
    $expectedId = [string]$assembly.logical_folder_ids.$name
    if ($folderId -ne $expectedId) { Fail "A1_RECOVERY_READBACK_LOGICAL_ID_MISMATCH:$name" }
    $files = @(Get-Children -ParentId $folderId -Headers $writerHeaders | Where-Object { [string]$_.mimeType -ne $FolderMime })
    $liveCount = $files.Count
    $liveFp = Get-NamesFingerprint -Items $files
    $expectedCount = [int]$assembly.readback.$name.file_count
    $expectedFp = [string]$assembly.readback.$name.names_fingerprint
    if ($liveCount -ne $expectedCount) { Fail "A1_RECOVERY_READBACK_FILE_COUNT_DRIFT:${name}:${liveCount}:$expectedCount" }
    if ($liveFp -ne $expectedFp) { Fail "A1_RECOVERY_READBACK_NAMES_FINGERPRINT_DRIFT:$name" }
    $liveLogical[$name] = [ordered]@{ folder_id = $folderId; file_count = $liveCount; names_fingerprint = $liveFp }
}

foreach ($checkName in @('manifest_count','physical_count','semantic_count','market_index_count','event_contract_nonempty')) {
    if ($assembly.checks.$checkName -ne $true) { Fail "A1_RECOVERY_READBACK_ASSEMBLY_CHECK_FALSE:$checkName" }
}

$checkpoints = @($m.Children | Where-Object { [string]$_.mimeType -ne $FolderMime -and [string]$_.name -like 'CHECKPOINT_*.json' } | Sort-Object { [string]$_.name })
if ($checkpoints.Count -lt 1) { Fail 'A1_RECOVERY_READBACK_CHECKPOINT_MISSING' }
$latestCpItem = $checkpoints[-1]
$cp = Get-FileJson -FileId ([string]$latestCpItem.id) -Headers $writerHeaders
if ([string]$cp.schema -ne 'A1_CANONICAL_CURRENT_RECOVERY_CHECKPOINT_V1') { Fail 'A1_RECOVERY_READBACK_CHECKPOINT_SCHEMA_MISMATCH' }
if ([string]$cp.status -ne 'PASS_PREPARED') { Fail "A1_RECOVERY_READBACK_CHECKPOINT_STATUS:$($cp.status)" }
if ([string]$cp.github_sha -ne $ExpectedRecoverySha) { Fail 'A1_RECOVERY_READBACK_CHECKPOINT_SHA_MISMATCH' }
if ([string]$cp.run_folder_id -ne $runId) { Fail 'A1_RECOVERY_READBACK_CHECKPOINT_RUN_ID_MISMATCH' }
if ([string]$cp.candidate_current_folder_id -ne $candidateId) { Fail 'A1_RECOVERY_READBACK_CHECKPOINT_CANDIDATE_ID_MISMATCH' }
if ([string]$cp.request_fingerprint -ne [string]$final.request_fingerprint -or [string]$cp.evidence_fingerprint -ne [string]$final.evidence_fingerprint) { Fail 'A1_RECOVERY_READBACK_CHECKPOINT_FINGERPRINT_MISMATCH' }
if ($cp.canonical_write_performed -ne $false -or $cp.raw_write_performed -ne $false) { Fail 'A1_RECOVERY_READBACK_CHECKPOINT_FORBIDDEN_WRITE_FLAG' }

$proof = [ordered]@{
    schema = 'A1_CANONICAL_CURRENT_RECOVERY_READBACK_V1'
    status = 'PASS_EXACT_RECOVERY_CANDIDATE_READBACK'
    pass = $true
    observed_at_utc = [DateTime]::UtcNow.ToString('o')
    machine = $env:COMPUTERNAME
    runner = $env:RUNNER_NAME
    recovery_github_sha = $ExpectedRecoverySha
    run_folder_id = $runId
    final_report_file_id = [string]$m.FinalItem.id
    final_status = [string]$final.status
    checkpoint_file_id = [string]$latestCpItem.id
    checkpoint_status = [string]$cp.status
    candidate_folder_id = $candidateId
    candidate_folder_role = [string]$assembly.candidate_folder_role
    recovered_source_count = [int]$final.recovered_source_count
    request_fingerprint = [string]$final.request_fingerprint
    evidence_fingerprint = [string]$final.evidence_fingerprint
    live_logical_folders = $liveLogical
    current_expected_missing_404 = $true
    reader_writer_distinct = $true
    drive_write_performed = $false
    raw_write_performed = $false
    canonical_current_mutation = $false
    canonical_promotion = $false
    heavy_behavior_research = $false
    secrets_disclosed = $false
}
$dir = Split-Path -Parent $ReportPath
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$proof | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $ReportPath -Encoding UTF8

Write-Host 'A1_CANONICAL_CURRENT_RECOVERY_READBACK_STATUS=PASS'
Write-Host "RECOVERY_GITHUB_SHA=$ExpectedRecoverySha"
Write-Host "RUN_FOLDER_ID=$runId"
Write-Host "CANDIDATE_FOLDER_ID=$candidateId"
Write-Host 'FINAL_REPORT=PASS_PREPARED_STAGING_ONLY'
Write-Host 'CHECKPOINT=PASS_PREPARED'
Write-Host 'LIVE_LOGICAL_FOLDER_READBACK=PASS'
Write-Host 'CURRENT_EXPECTED_MISSING_404=PASS'
Write-Host 'DRIVE_WRITE_PERFORMED=false'
Write-Host 'RAW_WRITE_PERFORMED=false'
Write-Host 'CANONICAL_CURRENT_MUTATION=false'
Write-Host 'CANONICAL_PROMOTION=false'
Write-Host 'HEAVY_BEHAVIOR_RESEARCH=false'
Write-Host 'SECRETS_DISCLOSED=false'
Write-Host "REPORT_PATH=$ReportPath"

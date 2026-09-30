[CmdletBinding()]
param(
    [string]$ExpectedRecoverySha = 'f621ccdc78dee31069a76cecfff26af80ef1681f'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$StagingId = '1WTb_lGBD6Tuwfcb-1WhsICjyJqzzBtwU'
$FolderMime = 'application/vnd.google-apps.folder'
$ReadWriteScope = 'https://www.googleapis.com/auth/drive'

function Fail([string]$Code) { throw $Code }
function UrlEncode([string]$Value) { [Uri]::EscapeDataString($Value) }

if ($env:COMPUTERNAME -ne 'PORSCHE-DESIGN') { Fail "A1_RECOVERY_INVENTORY_WRONG_MACHINE:$env:COMPUTERNAME" }
if ($env:RUNNER_NAME -ne 'A1-WINDOWS-COMPUTE-02') { Fail "A1_RECOVERY_INVENTORY_WRONG_RUNNER:$env:RUNNER_NAME" }

$writerPath = [string]$env:A1_DRIVE_WRITER_CREDENTIALS
if ([string]::IsNullOrWhiteSpace($writerPath) -or -not (Test-Path -LiteralPath $writerPath -PathType Leaf)) { Fail 'A1_RECOVERY_INVENTORY_WRITER_CREDENTIAL_MISSING' }
$c = Get-Content -LiteralPath $writerPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]$c.type -ne 'authorized_user') { Fail 'A1_RECOVERY_INVENTORY_UNSUPPORTED_CREDENTIAL_TYPE' }
$tokenUri = if (($c.PSObject.Properties.Name -contains 'token_uri') -and -not [string]::IsNullOrWhiteSpace([string]$c.token_uri)) { [string]$c.token_uri } else { 'https://oauth2.googleapis.com/token' }
$token = Invoke-RestMethod -Method Post -Uri $tokenUri -ContentType 'application/x-www-form-urlencoded' -Body @{
    client_id = [string]$c.client_id
    client_secret = [string]$c.client_secret
    refresh_token = [string]$c.refresh_token
    grant_type = 'refresh_token'
}
$access = [string]$token.access_token
if ([string]::IsNullOrWhiteSpace($access)) { Fail 'A1_RECOVERY_INVENTORY_REFRESH_NO_ACCESS_TOKEN' }
$info = Invoke-RestMethod -Method Get -Uri ('https://oauth2.googleapis.com/tokeninfo?access_token=' + (UrlEncode $access))
$scopes = @(([string]$info.scope) -split '\s+' | Where-Object { $_ })
if ($scopes -notcontains $ReadWriteScope) { Fail 'A1_RECOVERY_INVENTORY_WRITER_SCOPE_NOT_GRANTED' }
$headers = @{ Authorization = 'Bearer ' + $access }

function Query-Files([string]$Query) {
    $all = @()
    $page = $null
    do {
        $uri = 'https://www.googleapis.com/drive/v3/files?q=' + (UrlEncode $Query) + '&pageSize=1000&supportsAllDrives=true&includeItemsFromAllDrives=true&fields=' + (UrlEncode 'nextPageToken,files(id,name,mimeType,parents,trashed)')
        if ($page) { $uri += '&pageToken=' + (UrlEncode $page) }
        $res = Invoke-RestMethod -Method Get -Uri $uri -Headers $headers
        foreach ($item in @($res.files)) { $all += $item }
        $page = if ($res.PSObject.Properties.Name -contains 'nextPageToken') { [string]$res.nextPageToken } else { $null }
    } while (-not [string]::IsNullOrWhiteSpace($page))
    return $all
}

function Get-Children([string]$ParentId) {
    return @(Query-Files -Query ("'$ParentId' in parents and trashed=false"))
}

function Get-Json([string]$Id) {
    $uri = 'https://www.googleapis.com/drive/v3/files/' + $Id + '?alt=media&supportsAllDrives=true'
    return Invoke-RestMethod -Method Get -Uri $uri -Headers $headers
}

$rootChildren = @(Get-Children -ParentId $StagingId)
$directRuns = @($rootChildren | Where-Object { [string]$_.mimeType -eq $FolderMime -and [string]$_.name -like 'CANONICAL_CURRENT_RECOVERY_PREPARE_*' })
Write-Host "A1_RECOVERY_INVENTORY_STAGING_ROOT_CHILD_COUNT=$($rootChildren.Count)"
Write-Host "A1_RECOVERY_INVENTORY_DIRECT_RUN_COUNT=$($directRuns.Count)"

$globalRuns = @(Query-Files -Query "mimeType='$FolderMime' and name contains 'CANONICAL_CURRENT_RECOVERY_PREPARE_' and trashed=false")
Write-Host "A1_RECOVERY_INVENTORY_GLOBAL_RUN_COUNT=$($globalRuns.Count)"

$seen = @{}
foreach ($run in @($globalRuns | Sort-Object { [string]$_.name })) {
    $id = [string]$run.id
    if ($seen.ContainsKey($id)) { continue }
    $seen[$id] = $true
    $parents = @($run.parents) -join ','
    $direct = ($StagingId -in @($run.parents))
    $children = @(Get-Children -ParentId $id)
    $finalItems = @($children | Where-Object { [string]$_.name -eq 'RECOVERY_PREPARE_FINAL.json' -and [string]$_.mimeType -ne $FolderMime })
    $checkpoints = @($children | Where-Object { [string]$_.name -like 'CHECKPOINT_*.json' -and [string]$_.mimeType -ne $FolderMime } | Sort-Object { [string]$_.name })

    $finalSha = ''
    $finalStatus = ''
    $candidateId = ''
    if ($finalItems.Count -eq 1) {
        try {
            $final = Get-Json -Id ([string]$finalItems[0].id)
            $finalSha = [string]$final.github_sha
            $finalStatus = [string]$final.status
            if ($null -ne $final.assembly) { $candidateId = [string]$final.assembly.candidate_folder_id }
        } catch {
            $finalStatus = 'UNREADABLE'
        }
    } elseif ($finalItems.Count -gt 1) {
        $finalStatus = 'DUPLICATE_FINALS'
    } else {
        $finalStatus = 'NO_FINAL'
    }

    $cpStatus = ''
    $cpSha = ''
    $cpCandidate = ''
    if ($checkpoints.Count -gt 0) {
        try {
            $cp = Get-Json -Id ([string]$checkpoints[-1].id)
            $cpStatus = [string]$cp.status
            $cpSha = [string]$cp.github_sha
            $cpCandidate = [string]$cp.candidate_current_folder_id
        } catch {
            $cpStatus = 'UNREADABLE'
        }
    } else {
        $cpStatus = 'NO_CHECKPOINT'
    }

    Write-Host ('A1_RECOVERY_INVENTORY_RUN|' +
        'name=' + [string]$run.name +
        '|id=' + $id +
        '|direct_child_of_staging=' + $direct +
        '|parents=' + $parents +
        '|final_status=' + $finalStatus +
        '|final_sha=' + $finalSha +
        '|candidate_id=' + $candidateId +
        '|checkpoint_status=' + $cpStatus +
        '|checkpoint_sha=' + $cpSha +
        '|checkpoint_candidate_id=' + $cpCandidate)
}

$globalFinals = @(Query-Files -Query "name='RECOVERY_PREPARE_FINAL.json' and trashed=false")
Write-Host "A1_RECOVERY_INVENTORY_GLOBAL_FINAL_COUNT=$($globalFinals.Count)"
foreach ($item in $globalFinals) {
    try {
        $final = Get-Json -Id ([string]$item.id)
        Write-Host ('A1_RECOVERY_INVENTORY_FINAL|' +
            'id=' + [string]$item.id +
            '|parents=' + (@($item.parents) -join ',') +
            '|github_sha=' + [string]$final.github_sha +
            '|status=' + [string]$final.status +
            '|run_folder_id=' + [string]$final.run_folder_id +
            '|candidate_id=' + [string]$final.assembly.candidate_folder_id +
            '|expected_sha_match=' + ([string]$final.github_sha -eq $ExpectedRecoverySha))
    } catch {
        Write-Host ('A1_RECOVERY_INVENTORY_FINAL|id=' + [string]$item.id + '|status=UNREADABLE')
    }
}

Write-Host 'A1_RECOVERY_INVENTORY_STATUS=PASS_READ_ONLY'
Write-Host 'DRIVE_WRITE_PERFORMED=false'
Write-Host 'CANONICAL_CURRENT_MUTATION=false'
Write-Host 'SECRETS_DISCLOSED=false'

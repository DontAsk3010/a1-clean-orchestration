[CmdletBinding()]
param(
    [string]$OutputPath = "$HOME\.a1clean\writer-relocation-interactive-current.json"
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Get-Sha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-TextFingerprint([string]$Text) {
    if ([string]::IsNullOrWhiteSpace($Text)) { return 'NONE' }
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($Text)
        return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-','').ToLowerInvariant().Substring(0,16)
    } finally {
        $sha.Dispose()
    }
}

function Get-CredentialMetadata([System.IO.FileInfo]$File, [string]$ReaderHash) {
    if ($File.Length -lt 2 -or $File.Length -gt 4MB) { return $null }
    try {
        $payload = Get-Content -LiteralPath $File.FullName -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop
    } catch {
        return $null
    }
    if ($null -eq $payload) { return $null }

    $props = @($payload.PSObject.Properties.Name)
    $kind = $null
    $identity = ''
    $scopeState = 'UNKNOWN'
    $scopeCount = 0
    $driveWriteDeclared = $false
    $payloadType = if ($props -contains 'type') { [string]$payload.type } else { '' }

    if ($payloadType -eq 'authorized_user') {
        $kind = 'AUTHORIZED_USER_RUNTIME_CREDENTIAL'
        $identity = [string]$payload.client_id
    } elseif (($props -contains 'refresh_token') -and ($props -contains 'client_id') -and ($props -contains 'client_secret') -and ($props -contains 'token_uri')) {
        $kind = 'AUTHORIZED_USER_RUNTIME_CREDENTIAL_SHAPE'
        $identity = [string]$payload.client_id
    } elseif ($payloadType -eq 'service_account' -and ($props -contains 'client_email') -and ($props -contains 'private_key')) {
        $kind = 'SERVICE_ACCOUNT_RUNTIME_CREDENTIAL'
        $identity = [string]$payload.client_email
        $scopeState = 'SCOPES_RUNTIME_BOUND_NOT_STORED_IN_FILE'
    } elseif (($props -contains 'installed') -or ($props -contains 'web')) {
        $root = if ($props -contains 'installed') { $payload.installed } else { $payload.web }
        if ($null -ne $root -and @($root.PSObject.Properties.Name) -contains 'client_id') {
            $kind = 'OAUTH_CLIENT_CONFIG_NOT_RUNTIME_CREDENTIAL'
            $identity = [string]$root.client_id
            $scopeState = 'NOT_APPLICABLE_OAUTH_CLIENT_CONFIG'
        }
    }

    if (-not $kind) { return $null }

    if ($kind -in @('AUTHORIZED_USER_RUNTIME_CREDENTIAL','AUTHORIZED_USER_RUNTIME_CREDENTIAL_SHAPE')) {
        if ($props -contains 'scopes' -and $null -ne $payload.scopes) {
            $scopes = @($payload.scopes | ForEach-Object { [string]$_ })
            $scopeCount = $scopes.Count
            $driveWriteDeclared = $scopes -contains 'https://www.googleapis.com/auth/drive'
            $scopeState = if ($driveWriteDeclared) { 'DRIVE_WRITE_SCOPE_DECLARED' } else { 'SCOPES_DECLARED_NO_FULL_DRIVE_WRITE' }
        } else {
            $scopeState = 'SCOPE_NOT_DECLARED_IN_FILE'
        }
    }

    $hash = Get-Sha256 $File.FullName
    return [ordered]@{
        path = $File.FullName
        name = $File.Name
        size = [int64]$File.Length
        last_write_utc = $File.LastWriteTimeUtc.ToString('o')
        sha256 = $hash
        same_as_reader = [bool]($ReaderHash -and $hash -eq $ReaderHash)
        credential_kind = $kind
        payload_type = $payloadType
        identity_fp16 = Get-TextFingerprint $identity
        scope_state = $scopeState
        scope_count = $scopeCount
        drive_write_scope_declared = $driveWriteDeclared
    }
}

function Add-FileCandidate([System.Collections.Generic.Dictionary[string,System.IO.FileInfo]]$Map, [string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) { return }
    try {
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf -ErrorAction SilentlyContinue)) { return }
        $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
        $Map[$item.FullName.ToLowerInvariant()] = $item
    } catch {}
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$userName = [Environment]::UserName
$computer = $env:COMPUTERNAME
if ($computer -ne 'PORSCHE-DESIGN') {
    throw "WRONG_MACHINE: expected PORSCHE-DESIGN, observed $computer"
}
if ($userName -ne 'feri-admin') {
    throw "WRONG_INTERACTIVE_USER: expected feri-admin, observed $userName"
}

$writerBindings = [ordered]@{}
foreach ($scope in @('Process','User','Machine')) {
    $writerBindings[$scope] = [Environment]::GetEnvironmentVariable('A1_DRIVE_WRITER_CREDENTIALS',$scope)
}

$readerPath = $null
$readerScope = $null
foreach ($scope in @('Process','User','Machine')) {
    $p = [Environment]::GetEnvironmentVariable('A1_DRIVE_READER_CREDENTIALS',$scope)
    if ($p -and (Test-Path -LiteralPath $p -PathType Leaf -ErrorAction SilentlyContinue)) {
        $readerPath = (Get-Item -LiteralPath $p -Force).FullName
        $readerScope = $scope
        break
    }
}
if (-not $readerPath) {
    $fallback = 'C:\Users\feri-admin\a1-drive-auth\reader_credentials.json'
    if (Test-Path -LiteralPath $fallback -PathType Leaf -ErrorAction SilentlyContinue) {
        $readerPath = $fallback
        $readerScope = 'EXACT_FALLBACK_POSITIVE_CONTROL'
    }
}
if (-not $readerPath) {
    throw 'READER_POSITIVE_CONTROL_FILE_NOT_FOUND'
}
$readerHash = Get-Sha256 $readerPath

$files = New-Object 'System.Collections.Generic.Dictionary[string,System.IO.FileInfo]' ([StringComparer]::OrdinalIgnoreCase)

# 1) Exact environment/service references first.
foreach ($scope in $writerBindings.Keys) {
    Add-FileCandidate $files ([string]$writerBindings[$scope])
}
foreach ($svc in @(Get-CimInstance Win32_Service -ErrorAction SilentlyContinue | Where-Object {
    ([string]$_.DisplayName -like '*A1-WINDOWS-COMPUTE-02*') -or ([string]$_.PathName -like '*actions-runner-a1-02*')
})) {
    try {
        $regPath = "HKLM:\SYSTEM\CurrentControlSet\Services\$($svc.Name)"
        $reg = Get-ItemProperty -LiteralPath $regPath -ErrorAction Stop
        foreach ($entry in @($reg.Environment)) {
            if ([string]$entry -match '^A1_DRIVE_WRITER_CREDENTIALS=(.+)$') {
                Add-FileCandidate $files $Matches[1].Trim().Trim('"').Trim("'")
            }
        }
    } catch {}
}

# 2) High-confidence exact names throughout current user/project locations.
$exactNames = @(
    'client_writer.json','writer_oauth_client.json','writer_credentials.json','drive_writer.json',
    'google_drive_writer.json','oauth_writer.json','credentials_writer.json','client_secret_writer.json'
)
$roots = New-Object System.Collections.Generic.List[string]
foreach ($p in @(
    $HOME,
    "$HOME\Desktop",
    "$HOME\Documents",
    "$HOME\Downloads",
    "$HOME\.a1clean",
    "$HOME\a1-drive-auth",
    "$HOME\actions-runner-a1",
    "$HOME\actions-runner-a1-02",
    'C:\ProgramData',
    'D:\',
    'G:\'
)) {
    if ($p -and (Test-Path -LiteralPath $p -PathType Container -ErrorAction SilentlyContinue) -and -not $roots.Contains($p)) {
        [void]$roots.Add($p)
    }
}

foreach ($root in $roots) {
    foreach ($name in $exactNames) {
        try {
            Get-ChildItem -LiteralPath $root -File -Filter $name -Recurse -Force -ErrorAction SilentlyContinue |
                ForEach-Object { $files[$_.FullName.ToLowerInvariant()] = $_ }
        } catch {}
    }
}

# 3) Structural JSON search. This is the interactive-user step the service runner could not prove.
# Keep it bounded to small JSON and skip known package/cache trees.
$excludeRegex = '(?i)\\(node_modules|\.git|\.venv|venv|__pycache__|AppData\\Local\\Packages|AppData\\Local\\Google\\Chrome|AppData\\Local\\Microsoft\\Edge|AppData\\Local\\Temp|pip\\cache|npm-cache|NuGet\\Cache)\\'
$structuralRoots = New-Object System.Collections.Generic.List[string]
foreach ($p in @($HOME,'D:\')) {
    if ($p -and (Test-Path -LiteralPath $p -PathType Container -ErrorAction SilentlyContinue) -and -not $structuralRoots.Contains($p)) {
        [void]$structuralRoots.Add($p)
    }
}

$jsonSeen = 0
foreach ($root in $structuralRoots) {
    try {
        foreach ($file in @(Get-ChildItem -LiteralPath $root -File -Filter '*.json' -Recurse -Force -ErrorAction SilentlyContinue)) {
            if ($file.Length -lt 2 -or $file.Length -gt 4MB) { continue }
            if ($file.FullName -match $excludeRegex) { continue }
            $jsonSeen++
            $meta = Get-CredentialMetadata $file $readerHash
            if ($null -ne $meta) {
                $files[$file.FullName.ToLowerInvariant()] = $file
            }
        }
    } catch {}
}

# 4) Historical/current config references under user-owned text/config state.
$referenceFilesSeen = 0
$referenceHits = 0
$referenceRegex = '(?i)([A-Za-z]:\\[^"'';\r\n]+?\.json)'
foreach ($root in @($HOME, "$HOME\actions-runner-a1", "$HOME\actions-runner-a1-02")) {
    if (-not (Test-Path -LiteralPath $root -PathType Container -ErrorAction SilentlyContinue)) { continue }
    try {
        Get-ChildItem -LiteralPath $root -File -Recurse -Force -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Length -le 4MB -and $_.FullName -notmatch $excludeRegex -and
                $_.Extension -in @('.ps1','.psm1','.cmd','.bat','.env','.ini','.cfg','.conf','.txt','.json','.yml','.yaml','.log')
            } |
            ForEach-Object {
                $referenceFilesSeen++
                try {
                    $hits = @(Select-String -LiteralPath $_.FullName -Pattern 'A1_DRIVE_WRITER_CREDENTIALS|client_writer\.json|writer_oauth_client\.json|drive.*writer|writer.*drive' -CaseSensitive:$false -ErrorAction Stop)
                    foreach ($hit in $hits) {
                        $referenceHits++
                        foreach ($m in [regex]::Matches([string]$hit.Line,$referenceRegex)) {
                            Add-FileCandidate $files $m.Groups[1].Value
                        }
                    }
                } catch {}
            }
    } catch {}
}

# Always inject Reader positive control so detector correctness is proven in this exact interactive context.
$readerFile = Get-Item -LiteralPath $readerPath -Force
$files[$readerFile.FullName.ToLowerInvariant()] = $readerFile

$credentialRows = New-Object System.Collections.Generic.List[object]
foreach ($file in @($files.Values | Sort-Object FullName)) {
    $meta = Get-CredentialMetadata $file $readerHash
    if ($null -ne $meta) { [void]$credentialRows.Add([pscustomobject]$meta) }
}

$readerRows = @($credentialRows | Where-Object { $_.same_as_reader -eq $true })
$runtimeRows = @($credentialRows | Where-Object { $_.credential_kind -in @('AUTHORIZED_USER_RUNTIME_CREDENTIAL','AUTHORIZED_USER_RUNTIME_CREDENTIAL_SHAPE','SERVICE_ACCOUNT_RUNTIME_CREDENTIAL') })
$distinctRuntime = @($runtimeRows | Where-Object { $_.same_as_reader -ne $true })
$writerScopeRuntime = @($distinctRuntime | Where-Object { $_.drive_write_scope_declared -eq $true -or $_.credential_kind -eq 'SERVICE_ACCOUNT_RUNTIME_CREDENTIAL' })
$oauthConfigs = @($credentialRows | Where-Object { $_.credential_kind -eq 'OAUTH_CLIENT_CONFIG_NOT_RUNTIME_CREDENTIAL' })

if ($readerRows.Count -lt 1) {
    throw 'INTERACTIVE_STRUCTURAL_DETECTOR_POSITIVE_CONTROL_FAILED'
}

$status = if ($distinctRuntime.Count -gt 0) {
    'CANDIDATE_EXISTING_RUNTIME_CREDENTIAL_FOUND_REQUIRES_GOVERNED_VERIFICATION'
} else {
    'NO_DISTINCT_RUNTIME_CREDENTIAL_FOUND_IN_INTERACTIVE_RELOCATION_SCOPE'
}

$report = [ordered]@{
    schema = 'A1_DRIVE_WRITER_INTERACTIVE_RELOCATION_SEARCH_V1'
    status = $status
    observed_at_utc = [DateTime]::UtcNow.ToString('o')
    machine = $computer
    interactive_user = $userName
    windows_identity = $identity
    owner_corrected_blocker = 'HOLD_WRITER_CREDENTIAL_LOCATION_UNRESOLVED'
    mutation = $false
    binding_changed = $false
    drive_write = $false
    oauth_reauthorization = $false
    canonical_current_mutation = $false
    secrets_disclosed = $false
    writer_bindings = $writerBindings
    reader_positive_control = [ordered]@{
        path = $readerPath
        env_scope = $readerScope
        sha256 = $readerHash
        detected_by_structural_classifier = $true
    }
    search_scope = [ordered]@{
        roots = @($roots)
        structural_roots = @($structuralRoots)
        json_files_seen = $jsonSeen
        reference_files_seen = $referenceFilesSeen
        reference_hits = $referenceHits
        exact_names = $exactNames
    }
    counts = [ordered]@{
        credential_shape_candidates = $credentialRows.Count
        runtime_candidates = $runtimeRows.Count
        runtime_candidates_distinct_from_reader = $distinctRuntime.Count
        runtime_candidates_with_declared_write_or_service_account_scope_model = $writerScopeRuntime.Count
        oauth_client_configs = $oauthConfigs.Count
    }
    candidates = @($credentialRows | ForEach-Object {
        [ordered]@{
            path = $_.path
            name = $_.name
            size = $_.size
            last_write_utc = $_.last_write_utc
            sha256 = $_.sha256
            same_as_reader = $_.same_as_reader
            credential_kind = $_.credential_kind
            payload_type = $_.payload_type
            identity_fp16 = $_.identity_fp16
            scope_state = $_.scope_state
            scope_count = $_.scope_count
            drive_write_scope_declared = $_.drive_write_scope_declared
        }
    })
    next_exact_gate = if ($distinctRuntime.Count -gt 0) {
        'VERIFY_CANDIDATE_IDENTITY_TYPE_NOT_READER_AND_SCOPE_WITH_GOVERNED_INTAKE_BEFORE_BINDING'
    } else {
        'RECONCILE_INTERACTIVE_NO_CANDIDATE_RESULT_WITH_PRIOR_SERVICE_SEARCH_BEFORE_ANY_REAUTHORIZATION_OR_REPLACEMENT'
    }
}

$outDir = Split-Path -Parent $OutputPath
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $OutputPath -Encoding UTF8

Write-Host "A1_INTERACTIVE_WRITER_RELOCATION_SEARCH_COMPLETE"
Write-Host "REPORT_PATH=$OutputPath"
Write-Host "STATUS=$status"
Write-Host "READER_POSITIVE_CONTROL=PASS"
Write-Host "DISTINCT_RUNTIME_CANDIDATES=$($distinctRuntime.Count)"
Write-Host "OAUTH_CLIENT_CONFIGS=$($oauthConfigs.Count)"
Write-Host "SECRETS_DISCLOSED=false"
Write-Host "MUTATION=false"

[CmdletBinding()]
param(
    [string]$ReaderPath = 'C:\Users\feri-admin\a1-drive-auth\reader_credentials.json',
    [string]$ProofPath = 'C:\Users\feri-admin\.a1clean\reader-reauth-current.json'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ExpectedMachine = 'PORSCHE-DESIGN'
$ExpectedUser = 'feri-admin'
$ExpectedPrincipal = 'fjulie8satu@gmail.com'
$ReadOnlyScope = 'https://www.googleapis.com/auth/drive.readonly'
$FullDriveScope = 'https://www.googleapis.com/auth/drive'
$RawId = '1gTyt7CzqlubcdZGjWV_lM9Iw8Zg4ib3e'
$RawName = '02_CURRENT_HISTORICAL_RAW_DATA_UJI'

function Fail([string]$Code) { throw $Code }
function UrlEncode([string]$Value) { [Uri]::EscapeDataString($Value) }
function Get-Sha256([string]$Path) { (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }

if ($env:COMPUTERNAME -ne $ExpectedMachine) { Fail "A1_READER_REAUTH_WRONG_MACHINE:$env:COMPUTERNAME" }
if ([Environment]::UserName -ne $ExpectedUser) { Fail "A1_READER_REAUTH_WRONG_USER:$([Environment]::UserName)" }
if (-not (Test-Path -LiteralPath $ReaderPath -PathType Leaf)) { Fail 'A1_READER_REAUTH_CURRENT_READER_MISSING' }

$oldHash = Get-Sha256 $ReaderPath
$oldAcl = Get-Acl -LiteralPath $ReaderPath
$old = Get-Content -LiteralPath $ReaderPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]$old.type -ne 'authorized_user') { Fail 'A1_READER_REAUTH_UNSUPPORTED_CREDENTIAL_TYPE' }
foreach ($name in @('client_id','client_secret','refresh_token')) {
    if (-not ($old.PSObject.Properties.Name -contains $name) -or [string]::IsNullOrWhiteSpace([string]$old.$name)) {
        Fail "A1_READER_REAUTH_MISSING_$name"
    }
}

$runtimeClientId = [string]$old.client_id
$runtimeClientSecret = [string]$old.client_secret

# Reuse the original installed/desktop OAuth client config instead of treating
# the runtime authorized_user credential itself as the client definition.
$candidatePaths = New-Object System.Collections.Generic.List[string]
$writerReport = Join-Path $HOME '.a1clean\writer-relocation-interactive-current.json'
if (Test-Path -LiteralPath $writerReport -PathType Leaf) {
    try {
        $wr = Get-Content -LiteralPath $writerReport -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($c in @($wr.candidates)) {
            if ([string]$c.credential_kind -eq 'OAUTH_CLIENT_CONFIG_NOT_RUNTIME_CREDENTIAL') {
                $p = [string]$c.path
                if (-not [string]::IsNullOrWhiteSpace($p) -and (Test-Path -LiteralPath $p -PathType Leaf)) {
                    $candidatePaths.Add([IO.Path]::GetFullPath($p))
                }
            }
        }
    } catch {}
}

$roots = @(
    (Join-Path $HOME 'a1-drive-auth'),
    (Join-Path $HOME '.a1clean'),
    (Join-Path $HOME 'Documents'),
    (Join-Path $HOME 'Desktop'),
    (Join-Path $HOME 'Downloads')
) | Where-Object { Test-Path -LiteralPath $_ -PathType Container }

foreach ($root in $roots) {
    Get-ChildItem -LiteralPath $root -File -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -eq '.json' -and $_.Name -match 'client|oauth|secret|credential' } |
        ForEach-Object { $candidatePaths.Add($_.FullName) }
}

$installedMatches = New-Object System.Collections.Generic.List[object]
$webMatches = New-Object System.Collections.Generic.List[object]
$seenPaths = @{}
foreach ($path in @($candidatePaths | Sort-Object -Unique)) {
    if ($seenPaths.ContainsKey($path)) { continue }
    $seenPaths[$path] = $true
    try {
        $doc = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop
        if ($doc.PSObject.Properties.Name -contains 'installed') {
            $root = $doc.installed
            if ([string]$root.client_id -eq $runtimeClientId) {
                $installedMatches.Add([pscustomobject]@{ Path=$path; Root=$root })
            }
        }
        elseif ($doc.PSObject.Properties.Name -contains 'web') {
            $root = $doc.web
            if ([string]$root.client_id -eq $runtimeClientId) {
                $webMatches.Add([pscustomobject]@{ Path=$path; Root=$root })
            }
        }
    } catch {}
}

if ($installedMatches.Count -eq 0) {
    if ($webMatches.Count -gt 0) { Fail 'A1_READER_REAUTH_MATCHING_CLIENT_IS_WEB_NOT_DESKTOP' }
    Fail 'A1_READER_REAUTH_MATCHING_INSTALLED_CLIENT_CONFIG_NOT_FOUND'
}

# Multiple file copies are allowed only when they describe the same exact client.
$configKeys = @($installedMatches | ForEach-Object {
    $r = $_.Root
    ([string]$r.client_id) + '|' + ([string]$r.client_secret) + '|' + ([string]$r.auth_uri) + '|' + ([string]$r.token_uri)
} | Sort-Object -Unique)
if ($configKeys.Count -ne 1) { Fail "A1_READER_REAUTH_AMBIGUOUS_INSTALLED_CLIENT_CONFIG:$($configKeys.Count)" }

$selected = @($installedMatches | Sort-Object { $_.Path.Length }, Path)[0]
$clientRoot = $selected.Root
$clientId = [string]$clientRoot.client_id
$clientSecret = [string]$clientRoot.client_secret
$authUri = if ($clientRoot.auth_uri) { [string]$clientRoot.auth_uri } else { 'https://accounts.google.com/o/oauth2/v2/auth' }
$tokenUri = if ($clientRoot.token_uri) { [string]$clientRoot.token_uri } else { 'https://oauth2.googleapis.com/token' }

if ($clientId -ne $runtimeClientId) { Fail 'A1_READER_REAUTH_CLIENT_ID_DRIFT' }
if ($clientSecret -ne $runtimeClientSecret) { Fail 'A1_READER_REAUTH_CLIENT_SECRET_DRIFT' }
if ($authUri -notmatch '^https://accounts\.google\.com/') { Fail 'A1_READER_REAUTH_UNEXPECTED_AUTH_URI' }
if ($tokenUri -notmatch '^https://oauth2\.googleapis\.com/token$|^https://accounts\.google\.com/o/oauth2/token$') { Fail 'A1_READER_REAUTH_UNEXPECTED_TOKEN_URI' }

Write-Host 'A1_READER_REAUTH_OAUTH_CLIENT_TYPE=INSTALLED_DESKTOP_MATCH_PASS'
Write-Host 'A1_READER_REAUTH_SCOPE=DRIVE_READONLY_ONLY'
Write-Host 'A1_READER_REAUTH_NEW_OAUTH_CLIENT_CREATED=false'

# Dynamic loopback redirect is the established installed-app flow already used
# by the previously successful Writer reauthorization.
$tcp = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback,0)
$tcp.Start()
$port = ([System.Net.IPEndPoint]$tcp.LocalEndpoint).Port
$tcp.Stop()
$redirectUri = "http://127.0.0.1:$port/"
$state = [Guid]::NewGuid().ToString('N')
$authUrl = $authUri + '?' + (@(
    'client_id=' + (UrlEncode $clientId),
    'redirect_uri=' + (UrlEncode $redirectUri),
    'response_type=code',
    'scope=' + (UrlEncode $ReadOnlyScope),
    'access_type=offline',
    'prompt=consent',
    'login_hint=' + (UrlEncode $ExpectedPrincipal),
    'state=' + (UrlEncode $state)
) -join '&')

$listener = [System.Net.HttpListener]::new()
$listener.Prefixes.Add($redirectUri)
$listener.Start()
try {
    Write-Host 'A1_READER_REAUTH_BROWSER_OPENING=TRUE'
    Start-Process $authUrl
    $task = $listener.GetContextAsync()
    if (-not $task.Wait([TimeSpan]::FromMinutes(10))) { Fail 'A1_READER_REAUTH_BROWSER_CALLBACK_TIMEOUT' }
    $ctx = $task.Result
    $q = $ctx.Request.QueryString
    $returnedState = [string]$q['state']
    $authError = [string]$q['error']
    $code = [string]$q['code']
    $html = '<html><body><h3>A1 CLEAN Machine 2</h3><p>Reader authorization received. You may close this tab and return to the launcher.</p></body></html>'
    $bytes = [Text.Encoding]::UTF8.GetBytes($html)
    $ctx.Response.ContentType = 'text/html; charset=utf-8'
    $ctx.Response.ContentLength64 = $bytes.Length
    $ctx.Response.OutputStream.Write($bytes,0,$bytes.Length)
    $ctx.Response.OutputStream.Close()
    if ($returnedState -ne $state) { Fail 'A1_READER_REAUTH_OAUTH_STATE_MISMATCH' }
    if (-not [string]::IsNullOrWhiteSpace($authError)) { Fail "A1_READER_REAUTH_GOOGLE_AUTHORIZATION_ERROR:$authError" }
    if ([string]::IsNullOrWhiteSpace($code)) { Fail 'A1_READER_REAUTH_AUTHORIZATION_CODE_MISSING' }
}
finally {
    if ($listener.IsListening) { $listener.Stop() }
    $listener.Close()
}

$token = Invoke-RestMethod -Method Post -Uri $tokenUri -ContentType 'application/x-www-form-urlencoded' -Body @{
    code = $code
    client_id = $clientId
    client_secret = $clientSecret
    redirect_uri = $redirectUri
    grant_type = 'authorization_code'
}
$accessToken = [string]$token.access_token
$refreshToken = [string]$token.refresh_token
if ([string]::IsNullOrWhiteSpace($accessToken)) { Fail 'A1_READER_REAUTH_ACCESS_TOKEN_MISSING' }
if ([string]::IsNullOrWhiteSpace($refreshToken)) { Fail 'A1_READER_REAUTH_REFRESH_TOKEN_MISSING_AFTER_CONSENT' }

$tokenInfo = Invoke-RestMethod -Method Get -Uri ('https://oauth2.googleapis.com/tokeninfo?access_token=' + (UrlEncode $accessToken))
$scopes = @(([string]$tokenInfo.scope) -split '\s+' | Where-Object { $_ })
if ($scopes -notcontains $ReadOnlyScope) { Fail 'A1_READER_REAUTH_READONLY_SCOPE_NOT_GRANTED' }
if ($scopes -contains $FullDriveScope) { Fail 'A1_READER_REAUTH_FULL_DRIVE_SCOPE_FORBIDDEN' }

$headers = @{ Authorization = 'Bearer ' + $accessToken }
$about = Invoke-RestMethod -Method Get -Uri 'https://www.googleapis.com/drive/v3/about?fields=user(emailAddress)' -Headers $headers
if (([string]$about.user.emailAddress).ToLowerInvariant() -ne $ExpectedPrincipal) { Fail 'A1_READER_REAUTH_PRINCIPAL_MISMATCH' }
$rawFields = UrlEncode 'id,name,mimeType'
$raw = Invoke-RestMethod -Method Get -Uri "https://www.googleapis.com/drive/v3/files/$RawId?fields=$rawFields&supportsAllDrives=true" -Headers $headers
if ([string]$raw.id -ne $RawId -or [string]$raw.name -ne $RawName -or [string]$raw.mimeType -ne 'application/vnd.google-apps.folder') { Fail 'A1_READER_REAUTH_RAW_IDENTITY_FAIL' }

# Prove the refresh token itself before replacing the current Reader file.
$refreshProof = Invoke-RestMethod -Method Post -Uri $tokenUri -ContentType 'application/x-www-form-urlencoded' -Body @{
    client_id = $clientId
    client_secret = $clientSecret
    refresh_token = $refreshToken
    grant_type = 'refresh_token'
}
$refreshAccess = [string]$refreshProof.access_token
if ([string]::IsNullOrWhiteSpace($refreshAccess)) { Fail 'A1_READER_REAUTH_NEW_REFRESH_TOKEN_PROOF_FAIL' }
$refreshInfo = Invoke-RestMethod -Method Get -Uri ('https://oauth2.googleapis.com/tokeninfo?access_token=' + (UrlEncode $refreshAccess))
$refreshScopes = @(([string]$refreshInfo.scope) -split '\s+' | Where-Object { $_ })
if ($refreshScopes -notcontains $ReadOnlyScope -or $refreshScopes -contains $FullDriveScope) { Fail 'A1_READER_REAUTH_REFRESH_SCOPE_FAIL' }

$expiry = if ($token.expires_in) { [DateTime]::UtcNow.AddSeconds([int]$token.expires_in).ToString('o') } else { $null }
$newCredential = [ordered]@{
    type = 'authorized_user'
    token = $accessToken
    refresh_token = $refreshToken
    token_uri = $tokenUri
    client_id = $clientId
    client_secret = $clientSecret
    scopes = @($ReadOnlyScope)
    expiry = $expiry
}
$pending = $ReaderPath + '.pending'
$json = $newCredential | ConvertTo-Json -Depth 5
[IO.File]::WriteAllText($pending, $json, [Text.UTF8Encoding]::new($false))

$backup = $ReaderPath + '.pre-reauth.' + [DateTime]::UtcNow.ToString('yyyyMMddHHmmss') + '.bak'
Move-Item -LiteralPath $ReaderPath -Destination $backup
Move-Item -LiteralPath $pending -Destination $ReaderPath
Set-Acl -LiteralPath $ReaderPath -AclObject $oldAcl
$newHash = Get-Sha256 $ReaderPath
if ($newHash -eq $oldHash) { Fail 'A1_READER_REAUTH_HASH_UNCHANGED_UNEXPECTED' }

$proof = [ordered]@{
    schema = 'A1_DRIVE_READER_REAUTH_PROOF_V2'
    status = 'PASS_EXISTING_READER_REAUTHORIZED_READONLY'
    observed_at_utc = [DateTime]::UtcNow.ToString('o')
    machine = $ExpectedMachine
    interactive_user = $ExpectedUser
    installed_desktop_oauth_client_match = $true
    existing_oauth_client_reused = $true
    new_oauth_client_created = $false
    reader_scope = $ReadOnlyScope
    full_drive_scope_granted = $false
    principal_match = $true
    raw_identity_read_pass = $true
    new_refresh_token_proof_pass = $true
    old_reader_sha256 = $oldHash
    new_reader_sha256 = $newHash
    backup_created = $true
    reader_path_unchanged = $true
    service_binding_change_required = $false
    drive_write_performed = $false
    canonical_current_mutation = $false
    secrets_disclosed = $false
    next_exact_gate = 'RECOVERY_AWARE_DRIVE_GUARDRAIL_READBACK'
}
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ProofPath) | Out-Null
[IO.File]::WriteAllText($ProofPath, ($proof | ConvertTo-Json -Depth 6), [Text.UTF8Encoding]::new($false))

Write-Host 'A1_DRIVE_READER_REAUTH_STATUS=PASS_EXISTING_READER_REAUTHORIZED_READONLY'
Write-Host 'OAUTH_CLIENT_TYPE=INSTALLED_DESKTOP'
Write-Host 'EXISTING_OAUTH_CLIENT_REUSED=true'
Write-Host 'NEW_OAUTH_CLIENT_CREATED=false'
Write-Host 'DRIVE_SCOPE=READONLY_ONLY'
Write-Host 'RAW_IDENTITY_READ=PASS'
Write-Host 'NEW_REFRESH_TOKEN_PROOF=PASS'
Write-Host 'SERVICE_BINDING_CHANGE_REQUIRED=false'
Write-Host 'DRIVE_WRITE_PERFORMED=false'
Write-Host 'CANONICAL_CURRENT_MUTATION=false'
Write-Host 'SECRETS_DISCLOSED=false'
Write-Host "PROOF_PATH=$ProofPath"

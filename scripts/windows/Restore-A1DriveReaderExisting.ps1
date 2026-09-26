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
    if (-not ($old.PSObject.Properties.Name -contains $name) -or [string]::IsNullOrWhiteSpace([string]$old.$name)) { Fail "A1_READER_REAUTH_MISSING_$name" }
}

$clientId = [string]$old.client_id
$clientSecret = [string]$old.client_secret
$tokenUri = if (($old.PSObject.Properties.Name -contains 'token_uri') -and -not [string]::IsNullOrWhiteSpace([string]$old.token_uri)) { [string]$old.token_uri } else { 'https://oauth2.googleapis.com/token' }
$authUri = 'https://accounts.google.com/o/oauth2/v2/auth'
if ($tokenUri -notmatch '^https://oauth2\.googleapis\.com/token$|^https://accounts\.google\.com/o/oauth2/token$') { Fail 'A1_READER_REAUTH_UNEXPECTED_TOKEN_URI' }

# Reuse the exact existing OAuth client. No new client is created.
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
    'include_granted_scopes=false',
    'login_hint=' + (UrlEncode $ExpectedPrincipal),
    'state=' + (UrlEncode $state)
) -join '&')

$listener = [System.Net.HttpListener]::new()
$listener.Prefixes.Add($redirectUri)
$listener.Start()
try {
    Write-Host 'A1_READER_REAUTH_BROWSER_OPENING=TRUE'
    Write-Host 'A1_READER_REAUTH_SCOPE=DRIVE_READONLY_ONLY'
    Start-Process $authUrl
    $task = $listener.GetContextAsync()
    if (-not $task.Wait([TimeSpan]::FromMinutes(10))) { Fail 'A1_READER_REAUTH_BROWSER_CALLBACK_TIMEOUT' }
    $ctx = $task.Result
    $q = $ctx.Request.QueryString
    $returnedState = [string]$q['state']
    $authError = [string]$q['error']
    $code = [string]$q['code']
    $html = '<html><body><h3>A1 CLEAN Machine 2</h3><p>Reader authorization received. You may close this browser tab.</p></body></html>'
    $bytes = [Text.Encoding]::UTF8.GetBytes($html)
    $ctx.Response.ContentType = 'text/html; charset=utf-8'
    $ctx.Response.ContentLength64 = $bytes.Length
    $ctx.Response.OutputStream.Write($bytes,0,$bytes.Length)
    $ctx.Response.OutputStream.Close()
    if ($returnedState -ne $state) { Fail 'A1_READER_REAUTH_OAUTH_STATE_MISMATCH' }
    if (-not [string]::IsNullOrWhiteSpace($authError)) { Fail "A1_READER_REAUTH_GOOGLE_AUTHORIZATION_ERROR:$authError" }
    if ([string]::IsNullOrWhiteSpace($code)) { Fail 'A1_READER_REAUTH_AUTHORIZATION_CODE_MISSING' }
} finally {
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

# Prove scope, principal and RAW read capability before replacing the existing file.
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

# Prove the new refresh token itself before promotion.
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

# Keep the old credential as immutable local recovery evidence; replace only after every proof passed.
$backup = $ReaderPath + '.pre-reauth.' + [DateTime]::UtcNow.ToString('yyyyMMddHHmmss') + '.bak'
Move-Item -LiteralPath $ReaderPath -Destination $backup
Move-Item -LiteralPath $pending -Destination $ReaderPath
Set-Acl -LiteralPath $ReaderPath -AclObject $oldAcl
$newHash = Get-Sha256 $ReaderPath
if ($newHash -eq $oldHash) { Fail 'A1_READER_REAUTH_HASH_UNCHANGED_UNEXPECTED' }

$proof = [ordered]@{
    schema = 'A1_DRIVE_READER_REAUTH_PROOF_V1'
    status = 'PASS_EXISTING_READER_REAUTHORIZED_READONLY'
    observed_at_utc = [DateTime]::UtcNow.ToString('o')
    machine = $ExpectedMachine
    interactive_user = $ExpectedUser
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
$proofJson = $proof | ConvertTo-Json -Depth 6
[IO.File]::WriteAllText($ProofPath, $proofJson, [Text.UTF8Encoding]::new($false))

Write-Host 'A1_DRIVE_READER_REAUTH_STATUS=PASS_EXISTING_READER_REAUTHORIZED_READONLY'
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

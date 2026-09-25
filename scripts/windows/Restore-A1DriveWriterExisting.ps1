[CmdletBinding()]
param(
    [string]$InteractiveReport = "$HOME\.a1clean\writer-relocation-interactive-current.json",
    [string]$FinalWriterPath = "$HOME\a1-drive-auth\client_writer.json",
    [string]$VerificationReport = "$HOME\.a1clean\writer-relocation-verification-current.json",
    [string]$BindingProof = "$HOME\.a1clean\writer-binding-current.json"
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ExpectedMachine = 'PORSCHE-DESIGN'
$ExpectedUser = 'feri-admin'
$ExpectedPrincipal = 'fjulie8satu@gmail.com'
$ExpectedStagingId = '1WTb_lGBD6Tuwfcb-1WhsICjyJqzzBtwU'
$DriveScope = 'https://www.googleapis.com/auth/drive'

function Fail([string]$Code) { throw $Code }
function Get-Sha256([string]$Path) { (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }
function UrlEncode([string]$Value) { [Uri]::EscapeDataString($Value) }

if ($env:COMPUTERNAME -ne $ExpectedMachine) { Fail "A1_REAUTH_WRONG_MACHINE:$env:COMPUTERNAME" }
if ([Environment]::UserName -ne $ExpectedUser) { Fail "A1_REAUTH_WRONG_USER:$([Environment]::UserName)" }

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'A1_REAUTH_ELEVATION_REQUIRED=TRUE'
    $args = @('-NoProfile','-ExecutionPolicy','Bypass','-File',('"' + $PSCommandPath + '"'))
    Start-Process -FilePath 'powershell.exe' -ArgumentList ($args -join ' ') -Verb RunAs
    exit 0
}

if (-not (Test-Path -LiteralPath $InteractiveReport -PathType Leaf)) { Fail 'A1_REAUTH_INTERACTIVE_REPORT_MISSING' }
$r = Get-Content -LiteralPath $InteractiveReport -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]$r.schema -ne 'A1_DRIVE_WRITER_INTERACTIVE_RELOCATION_SEARCH_V1') { Fail 'A1_REAUTH_REPORT_SCHEMA_FAIL' }
if ([string]$r.machine -ne $ExpectedMachine -or [string]$r.interactive_user -ne $ExpectedUser) { Fail 'A1_REAUTH_REPORT_CONTEXT_FAIL' }
if ($r.reader_positive_control.detected_by_structural_classifier -ne $true) { Fail 'A1_REAUTH_READER_POSITIVE_CONTROL_FAIL' }

$runtimeKinds = @('AUTHORIZED_USER_RUNTIME_CREDENTIAL','AUTHORIZED_USER_RUNTIME_CREDENTIAL_SHAPE')
$runtime = @($r.candidates | Where-Object { $_.same_as_reader -ne $true -and $runtimeKinds -contains [string]$_.credential_kind })
$oauthConfigs = @($r.candidates | Where-Object { [string]$_.credential_kind -eq 'OAUTH_CLIENT_CONFIG_NOT_RUNTIME_CREDENTIAL' })
if ($runtime.Count -ne 1) { Fail "A1_REAUTH_EXPECTED_ONE_EXISTING_RUNTIME_WRITER:observed=$($runtime.Count)" }
if ($oauthConfigs.Count -ne 1) { Fail "A1_REAUTH_EXPECTED_ONE_EXISTING_OAUTH_CLIENT_CONFIG:observed=$($oauthConfigs.Count)" }
if ([string]$runtime[0].identity_fp16 -ne [string]$oauthConfigs[0].identity_fp16) { Fail 'A1_REAUTH_CLIENT_FINGERPRINT_MISMATCH' }

$expiredWriterPath = [string]$runtime[0].path
$oauthClientPath = [string]$oauthConfigs[0].path
$readerPath = [string]$r.reader_positive_control.path
foreach ($p in @($expiredWriterPath,$oauthClientPath,$readerPath)) {
    if ([string]::IsNullOrWhiteSpace($p) -or -not (Test-Path -LiteralPath $p -PathType Leaf)) { Fail "A1_REAUTH_REQUIRED_FILE_MISSING:$p" }
}
if ((Get-Sha256 $expiredWriterPath) -ne ([string]$runtime[0].sha256).ToLowerInvariant()) { Fail 'A1_REAUTH_EXPIRED_WRITER_HASH_DRIFT' }
if ((Get-Sha256 $readerPath) -ne ([string]$r.reader_positive_control.sha256).ToLowerInvariant()) { Fail 'A1_REAUTH_READER_HASH_DRIFT' }
if ((Get-Sha256 $expiredWriterPath) -eq (Get-Sha256 $readerPath)) { Fail 'A1_REAUTH_RUNTIME_CANDIDATE_IS_READER' }

$old = Get-Content -LiteralPath $expiredWriterPath -Raw -Encoding UTF8 | ConvertFrom-Json
$clientDoc = Get-Content -LiteralPath $oauthClientPath -Raw -Encoding UTF8 | ConvertFrom-Json
$clientRoot = $null
if ($clientDoc.PSObject.Properties.Name -contains 'installed') { $clientRoot = $clientDoc.installed }
elseif ($clientDoc.PSObject.Properties.Name -contains 'web') { Fail 'A1_REAUTH_EXISTING_CLIENT_IS_NOT_DESKTOP_INSTALLED_APP' }
else { Fail 'A1_REAUTH_OAUTH_CLIENT_CONFIG_SHAPE_FAIL' }

$clientId = [string]$clientRoot.client_id
$clientSecret = [string]$clientRoot.client_secret
$authUri = if ($clientRoot.auth_uri) { [string]$clientRoot.auth_uri } else { 'https://accounts.google.com/o/oauth2/v2/auth' }
$tokenUri = if ($clientRoot.token_uri) { [string]$clientRoot.token_uri } else { 'https://oauth2.googleapis.com/token' }
if ([string]::IsNullOrWhiteSpace($clientId) -or [string]::IsNullOrWhiteSpace($clientSecret)) { Fail 'A1_REAUTH_EXISTING_CLIENT_CONFIG_INCOMPLETE' }
if ([string]$old.client_id -ne $clientId) { Fail 'A1_REAUTH_EXISTING_RUNTIME_AND_OAUTH_CLIENT_ID_MISMATCH' }
if ($authUri -notmatch '^https://accounts\.google\.com/') { Fail 'A1_REAUTH_UNEXPECTED_AUTH_URI' }
if ($tokenUri -notmatch '^https://oauth2\.googleapis\.com/token$|^https://accounts\.google\.com/o/oauth2/token$') { Fail 'A1_REAUTH_UNEXPECTED_TOKEN_URI' }

# Allocate a local loopback port for the installed-app OAuth redirect.
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
    'scope=' + (UrlEncode $DriveScope),
    'access_type=offline',
    'prompt=consent',
    'include_granted_scopes=true',
    'login_hint=' + (UrlEncode $ExpectedPrincipal),
    'state=' + (UrlEncode $state)
) -join '&')

$listener = [System.Net.HttpListener]::new()
$listener.Prefixes.Add($redirectUri)
$listener.Start()
try {
    Write-Host 'A1_EXISTING_WRITER_REAUTH_BROWSER_OPENING=TRUE'
    Write-Host "A1_EXISTING_WRITER_EXPECTED_ACCOUNT=$ExpectedPrincipal"
    Start-Process $authUrl
    $task = $listener.GetContextAsync()
    if (-not $task.Wait([TimeSpan]::FromMinutes(8))) { Fail 'A1_REAUTH_BROWSER_CALLBACK_TIMEOUT' }
    $ctx = $task.Result
    $q = $ctx.Request.QueryString
    $returnedState = [string]$q['state']
    $authError = [string]$q['error']
    $code = [string]$q['code']
    $html = '<html><body><h3>A1 CLEAN Machine 2</h3><p>Authorization received. You may close this browser tab and return to PowerShell.</p></body></html>'
    $bytes = [Text.Encoding]::UTF8.GetBytes($html)
    $ctx.Response.ContentType = 'text/html; charset=utf-8'
    $ctx.Response.ContentLength64 = $bytes.Length
    $ctx.Response.OutputStream.Write($bytes,0,$bytes.Length)
    $ctx.Response.OutputStream.Close()
    if ($returnedState -ne $state) { Fail 'A1_REAUTH_OAUTH_STATE_MISMATCH' }
    if (-not [string]::IsNullOrWhiteSpace($authError)) { Fail "A1_REAUTH_GOOGLE_AUTHORIZATION_ERROR:$authError" }
    if ([string]::IsNullOrWhiteSpace($code)) { Fail 'A1_REAUTH_AUTHORIZATION_CODE_MISSING' }
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
if ([string]::IsNullOrWhiteSpace($accessToken)) { Fail 'A1_REAUTH_ACCESS_TOKEN_MISSING' }
if ([string]::IsNullOrWhiteSpace($refreshToken)) { Fail 'A1_REAUTH_REFRESH_TOKEN_MISSING_AFTER_CONSENT' }

# Read-only proof of scope and principal before any binding.
$tokenInfo = Invoke-RestMethod -Method Get -Uri ('https://oauth2.googleapis.com/tokeninfo?access_token=' + (UrlEncode $accessToken))
$scopes = @(([string]$tokenInfo.scope) -split '\s+' | Where-Object { $_ })
if ($scopes -notcontains $DriveScope) { Fail 'A1_REAUTH_FULL_DRIVE_SCOPE_NOT_GRANTED' }
$headers = @{ Authorization = 'Bearer ' + $accessToken }
$about = Invoke-RestMethod -Method Get -Uri 'https://www.googleapis.com/drive/v3/about?fields=user(displayName,emailAddress,permissionId)' -Headers $headers
$principalEmail = ([string]$about.user.emailAddress).ToLowerInvariant()
if ($principalEmail -ne $ExpectedPrincipal) { Fail "A1_REAUTH_PRINCIPAL_MISMATCH:$principalEmail" }
$fields = UrlEncode 'id,name,capabilities(canAddChildren,canEdit),permissions(type,role,emailAddress,displayName)'
$staging = Invoke-RestMethod -Method Get -Uri "https://www.googleapis.com/drive/v3/files/$ExpectedStagingId?fields=$fields&supportsAllDrives=true" -Headers $headers
if ([string]$staging.id -ne $ExpectedStagingId) { Fail 'A1_REAUTH_STAGING_READBACK_FAIL' }
$ownerMatches = @($staging.permissions | Where-Object { ([string]$_.role -eq 'owner') -and (([string]$_.emailAddress).ToLowerInvariant() -eq $ExpectedPrincipal) })
if ($ownerMatches.Count -lt 1) { Fail 'A1_REAUTH_STAGING_OWNER_PROOF_FAIL' }

$writerDir = Split-Path -Parent $FinalWriterPath
New-Item -ItemType Directory -Force -Path $writerDir | Out-Null
$pending = $FinalWriterPath + '.pending'
$expiry = if ($token.expires_in) { [DateTime]::UtcNow.AddSeconds([int]$token.expires_in).ToString('o') } else { $null }
$newCredential = [ordered]@{
    type = 'authorized_user'
    token = $accessToken
    refresh_token = $refreshToken
    token_uri = $tokenUri
    client_id = $clientId
    client_secret = $clientSecret
    scopes = @($DriveScope)
    expiry = $expiry
}
$newCredential | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $pending -Encoding UTF8

# Prove that the newly issued refresh token works before promoting the file.
$refreshProof = Invoke-RestMethod -Method Post -Uri $tokenUri -ContentType 'application/x-www-form-urlencoded' -Body @{
    client_id = $clientId
    client_secret = $clientSecret
    refresh_token = $refreshToken
    grant_type = 'refresh_token'
}
if ([string]::IsNullOrWhiteSpace([string]$refreshProof.access_token)) { Fail 'A1_REAUTH_NEW_REFRESH_TOKEN_PROOF_FAIL' }

if (Test-Path -LiteralPath $FinalWriterPath -PathType Leaf) {
    $backup = $FinalWriterPath + '.pre-reauth.' + [DateTime]::UtcNow.ToString('yyyyMMddHHmmss') + '.bak'
    Move-Item -LiteralPath $FinalWriterPath -Destination $backup -Force
}
Move-Item -LiteralPath $pending -Destination $FinalWriterPath -Force

# Mirror the proven Reader ACL so the Machine-2 service can read the Writer credential without broadening access.
$readerAcl = Get-Acl -LiteralPath $readerPath
Set-Acl -LiteralPath $FinalWriterPath -AclObject $readerAcl
$writerHash = Get-Sha256 $FinalWriterPath
$readerHash = Get-Sha256 $readerPath
if ($writerHash -eq $readerHash) { Fail 'A1_REAUTH_NEW_WRITER_EQUALS_READER' }

$verify = [ordered]@{
    schema = 'A1_DRIVE_WRITER_CANDIDATE_VERIFICATION_V2'
    status = 'PASS_REAUTHORIZED_EXISTING_WRITER_VERIFIED'
    observed_at_utc = [DateTime]::UtcNow.ToString('o')
    machine = $ExpectedMachine
    interactive_user = $ExpectedUser
    source_expired_writer_path = $expiredWriterPath
    source_existing_oauth_client_path = $oauthClientPath
    verified_writer_path = $FinalWriterPath
    verified_writer_sha256 = $writerHash
    reader_path = $readerPath
    reader_sha256 = $readerHash
    existing_client_id_match = $true
    new_oauth_client_created = $false
    oauth_reauthorization_performed = $true
    new_refresh_token_proof_pass = $true
    full_drive_scope_granted = $true
    principal_email = $principalEmail
    parity_staging_readback_pass = $true
    parity_staging_owner_principal_match = $true
    binding_changed = $false
    drive_write_performed = $false
    canonical_current_mutation = $false
    secrets_disclosed = $false
}
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $VerificationReport) | Out-Null
$verify | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $VerificationReport -Encoding UTF8

# Bind only the Machine-2 runner service. Do not set a machine-wide writer variable that could bleed into Machine 1.
$services = @(Get-CimInstance Win32_Service -ErrorAction Stop | Where-Object {
    ([string]$_.DisplayName -like '*A1-WINDOWS-COMPUTE-02*') -or ([string]$_.PathName -like '*actions-runner-a1-02*')
})
if ($services.Count -ne 1) { Fail "A1_REAUTH_MACHINE2_SERVICE_CARDINALITY:$($services.Count)" }
$svc = $services[0]
$regPath = "HKLM:\SYSTEM\CurrentControlSet\Services\$($svc.Name)"
$existingEnv = @()
try {
    $reg = Get-ItemProperty -LiteralPath $regPath -ErrorAction Stop
    if ($null -ne $reg.Environment) { $existingEnv = @($reg.Environment | ForEach-Object { [string]$_ }) }
} catch {}
$preserved = @($existingEnv | Where-Object { $_ -notmatch '^A1_DRIVE_WRITER_CREDENTIALS=' })
$newEnv = @($preserved + ("A1_DRIVE_WRITER_CREDENTIALS=" + $FinalWriterPath))
Set-ItemProperty -LiteralPath $regPath -Name Environment -Value $newEnv -Type MultiString
$readback = @((Get-ItemProperty -LiteralPath $regPath -Name Environment -ErrorAction Stop).Environment | Where-Object { $_ -match '^A1_DRIVE_WRITER_CREDENTIALS=' })
if ($readback.Count -ne 1) { Fail "A1_REAUTH_BINDING_READBACK_CARDINALITY:$($readback.Count)" }
if (([string]$readback[0]).Substring('A1_DRIVE_WRITER_CREDENTIALS='.Length) -ne $FinalWriterPath) { Fail 'A1_REAUTH_BINDING_READBACK_PATH_MISMATCH' }

$serviceName = [string]$svc.Name
Restart-Service -Name $serviceName -Force -ErrorAction Stop
$deadline = [DateTime]::UtcNow.AddSeconds(45)
do {
    Start-Sleep -Seconds 1
    $s = Get-Service -Name $serviceName
    if ($s.Status -eq 'Running') { break }
} while ([DateTime]::UtcNow -lt $deadline)
if ((Get-Service -Name $serviceName).Status -ne 'Running') { Fail 'A1_REAUTH_MACHINE2_SERVICE_RESTART_FAIL' }

$proof = [ordered]@{
    schema = 'A1_DRIVE_WRITER_VERIFIED_BINDING_V2'
    status = 'PASS_REAUTHORIZED_WRITER_BOUND_MACHINE2_SERVICE_RESTARTED'
    observed_at_utc = [DateTime]::UtcNow.ToString('o')
    machine = $ExpectedMachine
    target_runner = 'A1-WINDOWS-COMPUTE-02'
    service_name = $serviceName
    verified_writer_path = $FinalWriterPath
    verified_writer_sha256 = $writerHash
    reader_path = $readerPath
    reader_sha256 = $readerHash
    principal_email = $principalEmail
    full_drive_scope_granted = $true
    parity_staging_owner_proof = $true
    service_registry_binding_readback_pass = $true
    service_restart_pass = $true
    drive_write_performed = $false
    canonical_current_mutation = $false
    raw_write = $false
    secrets_disclosed = $false
    next_exact_gate = 'DRIVE_GUARDRAIL_PREFLIGHT'
}
$proof | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $BindingProof -Encoding UTF8

Write-Host 'A1_EXISTING_WRITER_REAUTH_STATUS=PASS'
Write-Host "PRINCIPAL_EMAIL=$principalEmail"
Write-Host 'FULL_DRIVE_SCOPE_GRANTED=True'
Write-Host 'PARITY_STAGING_OWNER_PROOF=PASS'
Write-Host "WRITER_PATH=$FinalWriterPath"
Write-Host 'NEW_OAUTH_CLIENT_CREATED=false'
Write-Host 'NEW_REFRESH_TOKEN_PROOF=PASS'
Write-Host 'MACHINE2_SERVICE_BINDING=PASS'
Write-Host 'MACHINE2_SERVICE_RESTART=PASS'
Write-Host 'DRIVE_WRITE_PERFORMED=false'
Write-Host 'CANONICAL_CURRENT_MUTATION=false'
Write-Host 'SECRETS_DISCLOSED=false'
Write-Host "VERIFICATION_REPORT=$VerificationReport"
Write-Host "BINDING_PROOF=$BindingProof"

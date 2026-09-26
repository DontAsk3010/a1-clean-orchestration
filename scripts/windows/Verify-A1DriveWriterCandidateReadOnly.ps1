param(
  [string]$ReportPath = 'C:\Users\feri-admin\.a1clean\writer-relocation-interactive-current.json',
  [string]$OutputPath = 'C:\Users\feri-admin\.a1clean\writer-relocation-verification-current.json'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ExpectedMachine = 'PORSCHE-DESIGN'
$ExpectedRunner = 'A1-WINDOWS-COMPUTE-02'
$ExpectedPrincipal = 'fjulie8satu@gmail.com'
$ExpectedStagingId = '1WTb_lGBD6Tuwfcb-1WhsICjyJqzzBtwU'
$DriveScope = 'https://www.googleapis.com/auth/drive'

function Fail([string]$Code) {
  throw $Code
}

function Get-SafeOAuthRefreshError($ErrorRecord) {
  $statusCode = $null
  $oauthError = 'UNKNOWN_OAUTH_ERROR'
  $oauthDescription = $null
  try {
    $resp = $ErrorRecord.Exception.Response
    if ($null -ne $resp) {
      try { $statusCode = [int]$resp.StatusCode } catch {}
      try {
        $stream = $resp.GetResponseStream()
        if ($null -ne $stream) {
          $reader = New-Object System.IO.StreamReader($stream)
          try {
            $body = $reader.ReadToEnd()
          } finally {
            $reader.Dispose()
          }
          if (-not [string]::IsNullOrWhiteSpace($body)) {
            try {
              $parsed = $body | ConvertFrom-Json
              if ($parsed.PSObject.Properties.Name -contains 'error') {
                $candidateError = [string]$parsed.error
                if ($candidateError -match '^[A-Za-z0-9_.-]{1,80}$') { $oauthError = $candidateError }
              }
              if ($parsed.PSObject.Properties.Name -contains 'error_description') {
                $candidateDescription = [string]$parsed.error_description
                if (-not [string]::IsNullOrWhiteSpace($candidateDescription)) {
                  # Allow only a compact human-readable description. Never echo request/body credentials.
                  $candidateDescription = ($candidateDescription -replace '[\r\n\t]+',' ')
                  if ($candidateDescription.Length -gt 240) { $candidateDescription = $candidateDescription.Substring(0,240) }
                  $oauthDescription = $candidateDescription
                }
              }
            } catch {}
          }
        }
      } catch {}
    }
  } catch {}
  return [pscustomobject]@{
    http_status = $statusCode
    oauth_error = $oauthError
    oauth_error_description = $oauthDescription
  }
}

if ($env:COMPUTERNAME -ne $ExpectedMachine) { Fail "A1_WRITER_VERIFY_WRONG_MACHINE:$env:COMPUTERNAME" }
if ($env:RUNNER_NAME -and $env:RUNNER_NAME -ne $ExpectedRunner) { Fail "A1_WRITER_VERIFY_WRONG_RUNNER:$env:RUNNER_NAME" }
if (-not (Test-Path -LiteralPath $ReportPath -PathType Leaf)) { Fail 'A1_WRITER_INTERACTIVE_REPORT_NOT_FOUND' }

$r = Get-Content -LiteralPath $ReportPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]$r.schema -ne 'A1_DRIVE_WRITER_INTERACTIVE_RELOCATION_SEARCH_V1') { Fail 'A1_WRITER_INTERACTIVE_REPORT_SCHEMA_FAIL' }
if ([string]$r.machine -ne $ExpectedMachine) { Fail 'A1_WRITER_INTERACTIVE_REPORT_MACHINE_FAIL' }
if ([string]$r.interactive_user -ne 'feri-admin') { Fail 'A1_WRITER_INTERACTIVE_REPORT_USER_FAIL' }
if ($r.reader_positive_control.detected_by_structural_classifier -ne $true) { Fail 'A1_WRITER_READER_POSITIVE_CONTROL_FAIL' }
foreach ($flag in @('mutation','binding_changed','drive_write','oauth_reauthorization','canonical_current_mutation','secrets_disclosed')) {
  if ($r.PSObject.Properties.Name -contains $flag) {
    if ($r.$flag -ne $false) { Fail "A1_WRITER_INTERACTIVE_UNSAFE_FLAG:$flag" }
  }
}

$readerPath = [string]$r.reader_positive_control.path
if (-not (Test-Path -LiteralPath $readerPath -PathType Leaf)) { Fail 'A1_WRITER_READER_FILE_MISSING' }
$readerHash = (Get-FileHash -LiteralPath $readerPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($readerHash -ne ([string]$r.reader_positive_control.sha256).ToLowerInvariant()) { Fail 'A1_WRITER_READER_HASH_DRIFT' }

$runtimeKinds = @('AUTHORIZED_USER_RUNTIME_CREDENTIAL','AUTHORIZED_USER_RUNTIME_CREDENTIAL_SHAPE')
$candidates = @($r.candidates | Where-Object {
  $_.same_as_reader -ne $true -and $runtimeKinds -contains [string]$_.credential_kind
})
if ($candidates.Count -ne 1) { Fail "A1_WRITER_VERIFY_EXPECTED_ONE_AUTHORIZED_USER_RUNTIME_CANDIDATE:observed=$($candidates.Count)" }

$c = $candidates[0]
$candidatePath = [string]$c.path
if (-not (Test-Path -LiteralPath $candidatePath -PathType Leaf)) { Fail 'A1_WRITER_CANDIDATE_FILE_MISSING' }
$candidateHash = (Get-FileHash -LiteralPath $candidatePath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($candidateHash -ne ([string]$c.sha256).ToLowerInvariant()) { Fail 'A1_WRITER_CANDIDATE_HASH_DRIFT' }
if ($candidateHash -eq $readerHash) { Fail 'A1_WRITER_CANDIDATE_BYTE_IDENTICAL_TO_READER' }

$credential = Get-Content -LiteralPath $candidatePath -Raw -Encoding UTF8 | ConvertFrom-Json
$props = @($credential.PSObject.Properties.Name)
foreach ($required in @('client_id','client_secret','refresh_token')) {
  if ($props -notcontains $required -or [string]::IsNullOrWhiteSpace([string]$credential.$required)) {
    Fail "A1_WRITER_CANDIDATE_MISSING_RUNTIME_FIELD:$required"
  }
}
$tokenUri = if (($props -contains 'token_uri') -and -not [string]::IsNullOrWhiteSpace([string]$credential.token_uri)) {
  [string]$credential.token_uri
} else {
  'https://oauth2.googleapis.com/token'
}
if ($tokenUri -notmatch '^https://oauth2\.googleapis\.com/token$|^https://accounts\.google\.com/o/oauth2/token$') {
  Fail 'A1_WRITER_CANDIDATE_UNEXPECTED_TOKEN_URI'
}

# Refresh only. This does not create a new grant or reauthorize OAuth.
try {
  $tokenResponse = Invoke-RestMethod -Method Post -Uri $tokenUri -ContentType 'application/x-www-form-urlencoded' -Body @{
    client_id = [string]$credential.client_id
    client_secret = [string]$credential.client_secret
    refresh_token = [string]$credential.refresh_token
    grant_type = 'refresh_token'
  }
} catch {
  $safe = Get-SafeOAuthRefreshError $_
  $failure = [ordered]@{
    schema = 'A1_DRIVE_WRITER_CANDIDATE_VERIFICATION_V1'
    status = 'FAIL_EXISTING_OAUTH_REFRESH_REJECTED'
    observed_at_utc = [DateTime]::UtcNow.ToString('o')
    machine = $ExpectedMachine
    runner = if ($env:RUNNER_NAME) { $env:RUNNER_NAME } else { 'INTERACTIVE_FERI_ADMIN' }
    interactive_report_path = $ReportPath
    candidate_path = $candidatePath
    candidate_sha256 = $candidateHash
    candidate_credential_kind = [string]$c.credential_kind
    reader_sha256 = $readerHash
    candidate_distinct_from_reader = $true
    oauth_refresh_pass = $false
    oauth_http_status = $safe.http_status
    oauth_error = $safe.oauth_error
    oauth_error_description = $safe.oauth_error_description
    binding_changed = $false
    drive_write_performed = $false
    oauth_reauthorization = $false
    canonical_current_mutation = $false
    secrets_disclosed = $false
  }
  $parent = Split-Path -Parent $OutputPath
  New-Item -ItemType Directory -Force -Path $parent | Out-Null
  $failure | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
  Write-Host 'A1_WRITER_CANDIDATE_VERIFY_STATUS=FAIL_EXISTING_OAUTH_REFRESH_REJECTED'
  Write-Host "OAUTH_HTTP_STATUS=$($safe.http_status)"
  Write-Host "OAUTH_ERROR=$($safe.oauth_error)"
  if (-not [string]::IsNullOrWhiteSpace([string]$safe.oauth_error_description)) {
    Write-Host "OAUTH_ERROR_DESCRIPTION=$($safe.oauth_error_description)"
  }
  Write-Host "VERIFICATION_REPORT=$OutputPath"
  Write-Host 'BINDING_CHANGED=false'
  Write-Host 'DRIVE_WRITE_PERFORMED=false'
  Write-Host 'OAUTH_REAUTHORIZATION=false'
  Write-Host 'CANONICAL_CURRENT_MUTATION=false'
  Write-Host 'SECRETS_DISCLOSED=false'
  exit 23
}

$accessToken = [string]$tokenResponse.access_token
if ([string]::IsNullOrWhiteSpace($accessToken)) { Fail 'A1_WRITER_CANDIDATE_REFRESH_NO_ACCESS_TOKEN' }

# Verify granted scopes without printing the token.
$tokenInfo = Invoke-RestMethod -Method Get -Uri ('https://oauth2.googleapis.com/tokeninfo?access_token=' + [Uri]::EscapeDataString($accessToken))
$scopeText = [string]$tokenInfo.scope
$scopes = @($scopeText -split '\s+' | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
$fullDriveScope = $scopes -contains $DriveScope
if (-not $fullDriveScope) { Fail 'A1_WRITER_CANDIDATE_FULL_DRIVE_SCOPE_NOT_GRANTED' }

$headers = @{ Authorization = 'Bearer ' + $accessToken }
$aboutUri = 'https://www.googleapis.com/drive/v3/about?fields=user(displayName,emailAddress,permissionId)'
$about = Invoke-RestMethod -Method Get -Uri $aboutUri -Headers $headers
$principalEmail = ([string]$about.user.emailAddress).ToLowerInvariant()
$principalName = [string]$about.user.displayName
$permissionId = [string]$about.user.permissionId
if ($principalEmail -ne $ExpectedPrincipal) { Fail "A1_WRITER_CANDIDATE_PRINCIPAL_MISMATCH:$principalEmail" }

# Read-only staging proof. No create/update/delete.
$fields = [Uri]::EscapeDataString('id,name,capabilities(canAddChildren,canEdit),permissions(type,role,emailAddress,displayName)')
$stagingUri = "https://www.googleapis.com/drive/v3/files/$ExpectedStagingId?fields=$fields&supportsAllDrives=true"
$staging = Invoke-RestMethod -Method Get -Uri $stagingUri -Headers $headers
if ([string]$staging.id -ne $ExpectedStagingId) { Fail 'A1_WRITER_CANDIDATE_STAGING_ID_READBACK_FAIL' }
$ownerMatches = @($staging.permissions | Where-Object {
  ([string]$_.role -eq 'owner') -and (([string]$_.emailAddress).ToLowerInvariant() -eq $ExpectedPrincipal)
})
if ($ownerMatches.Count -lt 1) { Fail 'A1_WRITER_CANDIDATE_STAGING_OWNER_PROOF_FAIL' }

$result = [ordered]@{
  schema = 'A1_DRIVE_WRITER_CANDIDATE_VERIFICATION_V1'
  status = 'PASS_EXACTLY_ONE_LEGITIMATE_EXISTING_WRITER_CANDIDATE'
  observed_at_utc = [DateTime]::UtcNow.ToString('o')
  machine = $ExpectedMachine
  runner = if ($env:RUNNER_NAME) { $env:RUNNER_NAME } else { 'INTERACTIVE_FERI_ADMIN' }
  interactive_report_path = $ReportPath
  candidate_path = $candidatePath
  candidate_sha256 = $candidateHash
  candidate_credential_kind = [string]$c.credential_kind
  reader_path = $readerPath
  reader_sha256 = $readerHash
  candidate_distinct_from_reader = $true
  oauth_refresh_pass = $true
  full_drive_scope_granted = $true
  granted_scope_count = $scopes.Count
  principal_email = $principalEmail
  principal_display_name = $principalName
  principal_permission_id_sha256_16 = if ($permissionId) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
      $b = [Text.Encoding]::UTF8.GetBytes($permissionId)
      (([BitConverter]::ToString($sha.ComputeHash($b))).Replace('-','').ToLowerInvariant()).Substring(0,16)
    } finally { $sha.Dispose() }
  } else { $null }
  parity_staging_folder_id = $ExpectedStagingId
  parity_staging_readback_pass = $true
  parity_staging_owner_principal_match = $true
  binding_changed = $false
  drive_write_performed = $false
  oauth_reauthorization = $false
  canonical_current_mutation = $false
  secrets_disclosed = $false
}

$parent = Split-Path -Parent $OutputPath
New-Item -ItemType Directory -Force -Path $parent | Out-Null
$result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $OutputPath -Encoding UTF8

Write-Host 'A1_WRITER_CANDIDATE_VERIFY_STATUS=PASS_EXACTLY_ONE_LEGITIMATE_EXISTING_WRITER_CANDIDATE'
Write-Host 'VERIFIED_LEGITIMATE_WRITER_CANDIDATES=1'
Write-Host "PRINCIPAL_EMAIL=$principalEmail"
Write-Host "FULL_DRIVE_SCOPE_GRANTED=$fullDriveScope"
Write-Host 'PARITY_STAGING_OWNER_PROOF=PASS'
Write-Host "VERIFICATION_REPORT=$OutputPath"
Write-Host 'BINDING_CHANGED=false'
Write-Host 'DRIVE_WRITE_PERFORMED=false'
Write-Host 'OAUTH_REAUTHORIZATION=false'
Write-Host 'CANONICAL_CURRENT_MUTATION=false'
Write-Host 'SECRETS_DISCLOSED=false'

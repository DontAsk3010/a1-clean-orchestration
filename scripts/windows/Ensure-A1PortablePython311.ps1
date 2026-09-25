[CmdletBinding()]
param(
    [string]$RuntimeRoot = 'C:\Users\feri-admin\.a1clean\runtime\python-3.11.9-embed-amd64',
    [string]$ProofPath = 'C:\Users\feri-admin\.a1clean\runtime\python-3.11.9-proof.json'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$PythonVersion = '3.11.9'
$PythonZipUrl = 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip'
$PythonZipExpectedMd5 = '6d9aa08531d48fcc261ba667e2df17c4'
$PipZipAppUrl = 'https://bootstrap.pypa.io/pip/pip.pyz'
$DownloadRoot = 'C:\Users\feri-admin\.a1clean\runtime\downloads'
$PythonZip = Join-Path $DownloadRoot 'python-3.11.9-embed-amd64.zip'
$PipPyz = Join-Path $RuntimeRoot 'pip.pyz'
$PythonExe = Join-Path $RuntimeRoot 'python.exe'
$SitePackages = Join-Path $RuntimeRoot 'Lib\site-packages'
$PthPath = Join-Path $RuntimeRoot 'python311._pth'
$VerifyScript = Join-Path $RuntimeRoot 'a1_verify_imports.py'

function Fail([string]$Code) { throw $Code }
function Hash([string]$Path,[string]$Algorithm) { (Get-FileHash -LiteralPath $Path -Algorithm $Algorithm).Hash.ToLowerInvariant() }

if ($env:COMPUTERNAME -ne 'PORSCHE-DESIGN') { Fail "A1_PORTABLE_PY_WRONG_MACHINE:$env:COMPUTERNAME" }
if ($env:RUNNER_NAME -and $env:RUNNER_NAME -ne 'A1-WINDOWS-COMPUTE-02') { Fail "A1_PORTABLE_PY_WRONG_RUNNER:$env:RUNNER_NAME" }

New-Item -ItemType Directory -Force -Path $DownloadRoot | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $RuntimeRoot) | Out-Null

$needExtract = $true
if (Test-Path -LiteralPath $PythonExe -PathType Leaf) {
    try {
        $versionText = (& $PythonExe --version 2>&1 | Out-String).Trim()
        if ($versionText -eq "Python $PythonVersion") { $needExtract = $false }
    } catch {}
}

if ($needExtract) {
    if (Test-Path -LiteralPath $RuntimeRoot) { Remove-Item -LiteralPath $RuntimeRoot -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null
    Write-Host 'A1_PORTABLE_PY_DOWNLOAD=PYTHON_EMBED'
    Invoke-WebRequest -UseBasicParsing -Uri $PythonZipUrl -OutFile $PythonZip
    $md5 = Hash $PythonZip 'MD5'
    $sha256 = Hash $PythonZip 'SHA256'
    if ($md5 -ne $PythonZipExpectedMd5) { Fail "A1_PORTABLE_PY_ARCHIVE_MD5_FAIL:observed=$md5" }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::ExtractToDirectory($PythonZip,$RuntimeRoot)
    Write-Host "A1_PORTABLE_PY_ARCHIVE_MD5_PASS=$md5"
    Write-Host "A1_PORTABLE_PY_ARCHIVE_SHA256=$sha256"
}

if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) { Fail 'A1_PORTABLE_PY_EXE_MISSING_AFTER_EXTRACT' }
$versionText = (& $PythonExe --version 2>&1 | Out-String).Trim()
if ($versionText -ne "Python $PythonVersion") { Fail "A1_PORTABLE_PY_VERSION_FAIL:$versionText" }

$pth = @(
    'python311.zip',
    '.',
    'Lib\site-packages',
    'import site'
) -join "`r`n"
Set-Content -LiteralPath $PthPath -Value ($pth + "`r`n") -Encoding ASCII
New-Item -ItemType Directory -Force -Path $SitePackages | Out-Null

if (-not (Test-Path -LiteralPath $PipPyz -PathType Leaf)) {
    Write-Host 'A1_PORTABLE_PY_DOWNLOAD=PIP_ZIPAPP'
    Invoke-WebRequest -UseBasicParsing -Uri $PipZipAppUrl -OutFile $PipPyz
}
$pipSha256 = Hash $PipPyz 'SHA256'

& $PythonExe $PipPyz install --disable-pip-version-check --upgrade --target $SitePackages `
    'setuptools>=69' wheel pytest google-auth google-api-python-client
if ($LASTEXITCODE -ne 0) { Fail "A1_PORTABLE_PY_DEPENDENCY_INSTALL_FAIL:$LASTEXITCODE" }

$verifyCode = @'
import json
import google.auth
import googleapiclient.discovery
import pytest
print(json.dumps({"python":"PASS","google_auth":"PASS","google_api_python_client":"PASS","pytest":"PASS"}, sort_keys=True))
'@
Set-Content -LiteralPath $VerifyScript -Value $verifyCode -Encoding ASCII
$previousPreference = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
$verifyLines = @(& $PythonExe $VerifyScript 2>&1)
$verifyExit = $LASTEXITCODE
$ErrorActionPreference = $previousPreference
$verifyOut = ($verifyLines | Out-String).Trim()
if ($verifyExit -ne 0) { Fail "A1_PORTABLE_PY_IMPORT_VERIFY_FAIL:exit=$verifyExit|output=$verifyOut" }
if ($verifyOut -notmatch '"python"\s*:\s*"PASS"') { Fail "A1_PORTABLE_PY_IMPORT_VERIFY_OUTPUT_FAIL:$verifyOut" }

$proof = [ordered]@{
    schema = 'A1_PORTABLE_PYTHON_RUNTIME_V1'
    status = 'PASS'
    observed_at_utc = [DateTime]::UtcNow.ToString('o')
    machine = $env:COMPUTERNAME
    runner = if ($env:RUNNER_NAME) { $env:RUNNER_NAME } else { 'INTERACTIVE' }
    python_version = $PythonVersion
    python_exe = $PythonExe
    runtime_root = $RuntimeRoot
    site_packages = $SitePackages
    pip_zipapp = $PipPyz
    pip_zipapp_sha256 = $pipSha256
    python_archive_source = $PythonZipUrl
    python_archive_expected_md5 = $PythonZipExpectedMd5
    python_archive_md5_verified = $true
    import_verification_script = $VerifyScript
    import_verification = $verifyOut
    machine_execution_policy_changed = $false
    registry_changed = $false
    drive_write_performed = $false
    canonical_current_mutation = $false
}
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ProofPath) | Out-Null
$proof | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $ProofPath -Encoding UTF8

Write-Host 'A1_PORTABLE_PYTHON_STATUS=PASS'
Write-Host "PYTHON_VERSION=$PythonVersion"
Write-Host "PYTHON_EXE=$PythonExe"
Write-Host "SITE_PACKAGES=$SitePackages"
Write-Host "PIP_PYZ=$PipPyz"
Write-Host "PIP_PYZ_SHA256=$pipSha256"
Write-Host "IMPORT_VERIFY_SCRIPT=$VerifyScript"
Write-Host 'MACHINE_EXECUTION_POLICY_CHANGED=false'
Write-Host 'REGISTRY_CHANGED=false'
Write-Host 'DRIVE_WRITE_PERFORMED=false'
Write-Host 'CANONICAL_CURRENT_MUTATION=false'
Write-Host "PROOF_PATH=$ProofPath"

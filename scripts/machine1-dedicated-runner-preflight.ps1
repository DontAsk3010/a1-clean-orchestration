param(
    [Parameter(Mandatory=$true)][string]$RawFile,
    [Parameter(Mandatory=$true)][string]$ExpectedMd5,
    [Parameter(Mandatory=$true)][string]$ExpectedSha256
)

$ErrorActionPreference = 'Stop'

Write-Host 'A1_MACHINE1_DEDICATED_RUNNER_PREFLIGHT_START'
Write-Host "RUNNER_NAME=$env:RUNNER_NAME"
Write-Host "RUNNER_OS=$env:RUNNER_OS"
Write-Host "RUNNER_ARCH=$env:RUNNER_ARCH"

if ($env:RUNNER_OS -ne 'Windows') {
    throw "RUNNER_OS_MISMATCH expected=Windows actual=$env:RUNNER_OS"
}

$py = & py -3.11 -c "import sys; print(sys.version.split()[0])"
if ($LASTEXITCODE -ne 0) {
    throw 'PYTHON_3_11_UNAVAILABLE'
}
Write-Host "PYTHON_3_11=$py"

if (-not (Test-Path -LiteralPath $RawFile -PathType Leaf)) {
    throw "RAW_MISSING:$RawFile"
}

$md5 = (Get-FileHash -LiteralPath $RawFile -Algorithm MD5).Hash.ToLowerInvariant()
$sha256 = (Get-FileHash -LiteralPath $RawFile -Algorithm SHA256).Hash.ToLowerInvariant()

if ($md5 -ne $ExpectedMd5.ToLowerInvariant()) {
    throw "RAW_MD5_MISMATCH expected=$ExpectedMd5 actual=$md5"
}
if ($sha256 -ne $ExpectedSha256.ToLowerInvariant()) {
    throw "RAW_SHA256_MISMATCH expected=$ExpectedSha256 actual=$sha256"
}

Write-Host "RAW_IDENTITY_PASS md5=$md5 sha256=$sha256"
Write-Host 'NO_DRIVE_WRITE=TRUE'
Write-Host 'NO_REGISTRY_WRITE=TRUE'
Write-Host 'NO_SEMANTIC_INTERPRETATION=TRUE'
Write-Host 'NO_LANE2_EXECUTION=TRUE'
Write-Host 'A1_MACHINE1_DEDICATED_RUNNER_PREFLIGHT_PASS'

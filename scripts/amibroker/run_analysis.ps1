param(
    [Parameter(Mandatory=$true)][string]$ProjectPath,
    [Parameter(Mandatory=$true)][string]$OutputCsv,
    [ValidateSet('SCAN','EXPLORE','PORTFOLIO_BACKTEST','INDIVIDUAL_BACKTEST','PORTFOLIO_OPTIMIZE','INDIVIDUAL_OPTIMIZE','WALK_FORWARD')]
    [string]$Action = 'EXPLORE',
    [int]$PollMilliseconds = 1000,
    [int]$TimeoutSeconds = 3600,
    [switch]$QuitApplication
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $ProjectPath -PathType Leaf)) {
    throw "APX_NOT_FOUND:$ProjectPath"
}
if ([IO.Path]::GetExtension($ProjectPath).ToLowerInvariant() -ne '.apx') {
    throw "PROJECT_MUST_BE_APX:$ProjectPath"
}

$actionMap = @{
    'SCAN' = 0
    'EXPLORE' = 1
    'PORTFOLIO_BACKTEST' = 2
    'INDIVIDUAL_BACKTEST' = 3
    'PORTFOLIO_OPTIMIZE' = 4
    'INDIVIDUAL_OPTIMIZE' = 5
    'WALK_FORWARD' = 6
}
$actionCode = [int]$actionMap[$Action]

$outDir = Split-Path -Parent ([IO.Path]::GetFullPath($OutputCsv))
if ($outDir -and -not (Test-Path -LiteralPath $outDir)) {
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
}

$ab = $null
$doc = $null
$created = $false
try {
    # External OLE automation only. No OLE calls are made from AFL itself.
    $ab = New-Object -ComObject 'Broker.Application'
    $created = $true
    $projectFull = [IO.Path]::GetFullPath($ProjectPath)
    $doc = $ab.AnalysisDocs.Open($projectFull)
    if ($null -eq $doc) { throw "AMIBROKER_APX_OPEN_FAILED:$projectFull" }
    if ($doc.IsBusy) { throw 'AMIBROKER_ANALYSIS_ALREADY_BUSY' }

    $started = $doc.Run($actionCode)
    if ([int]$started -ne 1) { throw "AMIBROKER_RUN_FAILED:ACTION=$Action" }

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ($doc.IsBusy) {
        if ([DateTime]::UtcNow -gt $deadline) {
            try { $doc.Abort() } catch {}
            throw "AMIBROKER_RUN_TIMEOUT:$TimeoutSeconds"
        }
        Start-Sleep -Milliseconds $PollMilliseconds
    }

    $outputFull = [IO.Path]::GetFullPath($OutputCsv)
    $exported = $doc.Export($outputFull, 0)
    if ([int]$exported -ne 1) { throw "AMIBROKER_EXPORT_FAILED:$outputFull" }
    if (-not (Test-Path -LiteralPath $outputFull -PathType Leaf)) { throw "AMIBROKER_EXPORT_MISSING:$outputFull" }

    [ordered]@{
        pass = $true
        action = $Action
        project = $projectFull
        output = $outputFull
        amibroker_version = [string]$ab.Version
        database_path = [string]$ab.DatabasePath
    } | ConvertTo-Json -Depth 5
}
finally {
    if ($null -ne $doc) {
        try {
            if ($doc.IsBusy) { $doc.Abort() }
            $doc.Close()
        } catch {}
    }
    if ($QuitApplication -and $created -and $null -ne $ab) {
        try { $ab.Quit() } catch {}
    }
    if ($null -ne $doc) { [Runtime.InteropServices.Marshal]::FinalReleaseComObject($doc) | Out-Null }
    if ($null -ne $ab) { [Runtime.InteropServices.Marshal]::FinalReleaseComObject($ab) | Out-Null }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}

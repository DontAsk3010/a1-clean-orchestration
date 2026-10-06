[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$Repository = 'DontAsk3010/a1-clean-orchestration',

    [Parameter(Mandatory = $false)]
    [string]$TargetRunnerName = 'A1-WINDOWS-COMPUTE-02',

    [Parameter(Mandatory = $false)]
    [string]$TargetLabel = 'a1-machine2-exact'
)

$ErrorActionPreference = 'Stop'

$token = [Environment]::GetEnvironmentVariable('A1_GITHUB_RUNNER_ADMIN_TOKEN', 'Process')
if ([string]::IsNullOrWhiteSpace($token)) {
    $token = [Environment]::GetEnvironmentVariable('A1_GITHUB_RUNNER_ADMIN_TOKEN', 'Machine')
}
if ([string]::IsNullOrWhiteSpace($token)) {
    $token = [Environment]::GetEnvironmentVariable('A1_GITHUB_RUNNER_ADMIN_TOKEN', 'User')
}
if ([string]::IsNullOrWhiteSpace($token)) {
    throw 'A1_GITHUB_RUNNER_ADMIN_TOKEN is not configured. No credential value is read from repo or printed.'
}

$headers = @{
    Authorization = "Bearer $token"
    Accept = 'application/vnd.github+json'
    'X-GitHub-Api-Version' = '2022-11-28'
}

try {
    $api = "https://api.github.com/repos/$Repository/actions/runners"
    $runners = Invoke-RestMethod -Method Get -Uri "$api?per_page=100" -Headers $headers

    $targets = @($runners.runners | Where-Object { [string]$_.name -eq $TargetRunnerName })
    if ($targets.Count -ne 1) {
        throw "TARGET_RUNNER_RESOLUTION_HOLD:name=$TargetRunnerName|count=$($targets.Count)"
    }

    $target = $targets[0]
    $targetId = [int64]$target.id
    Write-Host "TARGET_RUNNER_ID=$targetId"
    Write-Host "TARGET_RUNNER_STATUS=$($target.status)"
    Write-Host "TARGET_RUNNER_BUSY=$($target.busy)"

    $body = @{ labels = @($TargetLabel) } | ConvertTo-Json -Compress
    Invoke-RestMethod -Method Post -Uri "$api/$targetId/labels" -Headers $headers -ContentType 'application/json' -Body $body | Out-Null

    $targetReadback = Invoke-RestMethod -Method Get -Uri "$api/$targetId/labels" -Headers $headers
    $targetLabels = @($targetReadback.labels | ForEach-Object { [string]$_.name })
    if ($TargetLabel -notin $targetLabels) {
        throw "TARGET_LABEL_READBACK_HOLD:label=$TargetLabel"
    }

    $collisions = @()
    foreach ($runner in @($runners.runners)) {
        if ([int64]$runner.id -eq $targetId) { continue }
        $other = Invoke-RestMethod -Method Get -Uri "$api/$($runner.id)/labels" -Headers $headers
        $names = @($other.labels | ForEach-Object { [string]$_.name })
        if ($TargetLabel -in $names) {
            $collisions += [pscustomobject]@{
                runner_id = [int64]$runner.id
                runner_name = [string]$runner.name
            }
        }
    }

    if ($collisions.Count -ne 0) {
        $collisionText = ($collisions | ForEach-Object { "$($_.runner_name):$($_.runner_id)" }) -join ','
        throw "UNIQUE_LABEL_COLLISION_HOLD:$collisionText"
    }

    Write-Host 'A1_MACHINE2_EXACT_RUNNER_LABEL_PASS=true'
    Write-Host "A1_MACHINE2_EXACT_RUNNER_NAME=$TargetRunnerName"
    Write-Host "A1_MACHINE2_EXACT_RUNNER_SELECTOR=self-hosted,windows,x64,$TargetLabel"
}
finally {
    $token = $null
    $headers = $null
    $runners = $null
}

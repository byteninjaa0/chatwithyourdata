# Build and push all Docker images to Azure Container Registry (no deploy).
#
# Usage:
#   .\deploy\azure\build.ps1
#   .\deploy\azure\build.ps1 -Tag v2

param(
    [string]$Tag = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot

function Load-Config {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        throw "Config not found: $Path"
    }
    $cfg = @{}
    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if ($line -eq "" -or $line.StartsWith("#")) { return }
        $idx = $line.IndexOf("=")
        if ($idx -lt 1) { return }
        $cfg[$line.Substring(0, $idx).Trim()] = $line.Substring($idx + 1).Trim()
    }
    return $cfg
}

$cfg = Load-Config (Join-Path $PSScriptRoot "config.env")
$imageTag = if ($Tag) { $Tag } else { $cfg.IMAGE_TAG }
$acr = $cfg.AZURE_ACR_NAME
$rg = $cfg.AZURE_RESOURCE_GROUP

$acrServer = az acr show --name $acr --resource-group $rg --query loginServer -o tsv
if ($LASTEXITCODE -ne 0) { throw "ACR not found. Run deploy.ps1 -InfrastructureOnly first." }

az acr login --name $acr
if ($LASTEXITCODE -ne 0) { throw "ACR login failed" }

$images = @(
    @{ File = "Dockerfile.backend"; Name = "chatwithyourdata-backend" },
    @{ File = "Dockerfile.agent";   Name = "chatwithyourdata-agent" },
    @{ File = "Dockerfile.web";     Name = "chatwithyourdata-web" }
)

foreach ($img in $images) {
    $fullTag = "$acrServer/$($img.Name):$imageTag"
    Write-Host "Building $fullTag" -ForegroundColor Cyan
    docker build -f $img.File -t $fullTag .
    if ($LASTEXITCODE -ne 0) { throw "Build failed: $($img.File)" }
    docker push $fullTag
    if ($LASTEXITCODE -ne 0) { throw "Push failed: $fullTag" }
}

Write-Host "Done. Images tagged :$imageTag" -ForegroundColor Green

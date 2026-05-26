# Azure Container Apps — build, push, and deploy all three services.
#
# Prerequisites:
#   az login
#   Docker Desktop running
#
# Setup:
#   cp deploy/azure/config.example.env deploy/azure/config.env
#   # Edit deploy/azure/config.env with your secrets
#
# Usage:
#   .\deploy\azure\deploy.ps1
#   .\deploy\azure\deploy.ps1 -SkipBuild          # redeploy existing images only
#   .\deploy\azure\deploy.ps1 -InfrastructureOnly # create Azure resources, no deploy

param(
    [switch]$SkipBuild,
    [switch]$InfrastructureOnly
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Load-Config {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        throw "Config not found: $Path`nCopy deploy/azure/config.example.env to deploy/azure/config.env and fill in values."
    }
    $cfg = @{}
    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if ($line -eq "" -or $line.StartsWith("#")) { return }
        $idx = $line.IndexOf("=")
        if ($idx -lt 1) { return }
        $key = $line.Substring(0, $idx).Trim()
        $val = $line.Substring($idx + 1).Trim()
        $cfg[$key] = $val
    }
    return $cfg
}

function Require-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name is required but not found in PATH."
    }
}

function Invoke-Az([string[]]$Args) {
    $result = & az @Args
    if ($LASTEXITCODE -ne 0) {
        throw "az $($Args -join ' ') failed with exit code $LASTEXITCODE"
    }
    return $result
}

function Test-ContainerApp([string]$Name, [string]$ResourceGroup) {
    az containerapp show --name $Name --resource-group $ResourceGroup --output none 2>$null
    return $LASTEXITCODE -eq 0
}

function Ensure-ContainerApp {
    param(
        [hashtable]$Cfg,
        [string]$Name,
        [string]$Image,
        [int]$Port,
        [string]$Ingress,   # internal | external
        [string]$Cpu,
        [string]$Memory,
        [string[]]$SecretArgs,
        [string[]]$EnvArgs
    )

    $rg = $Cfg.AZURE_RESOURCE_GROUP
    $envName = $Cfg.AZURE_CONTAINERAPPS_ENV
    $acr = $Cfg.AZURE_ACR_NAME
    $acrServer = Invoke-Az acr show --name $acr --resource-group $rg --query loginServer -o tsv
    $acrUser = Invoke-Az acr credential show --name $acr --query username -o tsv
    $acrPass = Invoke-Az acr credential show --name $acr --query "passwords[0].value" -o tsv

    if (Test-ContainerApp -Name $Name -ResourceGroup $rg) {
        Write-Step "Updating container app: $Name"
        if ($SecretArgs.Count -gt 0) {
            Invoke-Az containerapp secret set --name $Name --resource-group $rg --secrets @SecretArgs | Out-Null
        }
        Invoke-Az containerapp update `
            --name $Name `
            --resource-group $rg `
            --image $Image `
            --cpu $Cpu `
            --memory $Memory `
            --set-env-vars @EnvArgs | Out-Null
    } else {
        Write-Step "Creating container app: $Name"
        $createArgs = @(
            "containerapp", "create",
            "--name", $Name,
            "--resource-group", $rg,
            "--environment", $envName,
            "--image", $Image,
            "--registry-server", $acrServer,
            "--registry-username", $acrUser,
            "--registry-password", $acrPass,
            "--target-port", "$Port",
            "--ingress", $Ingress,
            "--min-replicas", "1",
            "--max-replicas", "3",
            "--cpu", $Cpu,
            "--memory", $Memory
        )
        if ($SecretArgs.Count -gt 0) {
            $createArgs += @("--secrets") + $SecretArgs
            $createArgs += @("--env-vars") + $EnvArgs
        } else {
            $createArgs += @("--env-vars") + $EnvArgs
        }
        Invoke-Az @createArgs | Out-Null
    }
}

# ── Preflight ───────────────────────────────────────────────────────────────
Require-Command az

Write-Step "Loading config"
$ConfigPath = Join-Path $PSScriptRoot "config.env"
$cfg = Load-Config -Path $ConfigPath

foreach ($key in @(
    "AZURE_RESOURCE_GROUP", "AZURE_LOCATION", "AZURE_ACR_NAME",
    "AZURE_CONTAINERAPPS_ENV", "AZURE_LOG_ANALYTICS",
    "APP_BACKEND", "APP_AGENT", "APP_WEB", "IMAGE_TAG",
    "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY",
    "AIRTABLE_BASE_ID", "AIRTABLE_TOKEN"
)) {
    if (-not $cfg[$key]) {
        throw "Missing required config value: $key (in deploy/azure/config.env)"
    }
}

$RG       = $cfg.AZURE_RESOURCE_GROUP
$LOCATION = $cfg.AZURE_LOCATION
$ACR      = $cfg.AZURE_ACR_NAME
$ENV_NAME = $cfg.AZURE_CONTAINERAPPS_ENV
$LAW      = $cfg.AZURE_LOG_ANALYTICS
$TAG      = $cfg.IMAGE_TAG

# ── Infrastructure ────────────────────────────────────────────────────────────
Write-Step "Ensuring resource group: $RG"
Invoke-Az group create --name $RG --location $LOCATION --output none | Out-Null

Write-Step "Ensuring Azure Container Registry: $ACR"
$acrExists = az acr show --name $ACR --resource-group $RG 2>$null
if ($LASTEXITCODE -ne 0) {
    Invoke-Az acr create --resource-group $RG --name $ACR --sku Basic --admin-enabled true --output none
}

Write-Step "Ensuring Log Analytics workspace: $LAW"
$lawExists = az monitor log-analytics workspace show --resource-group $RG --workspace-name $LAW 2>$null
if ($LASTEXITCODE -ne 0) {
    Invoke-Az monitor log-analytics workspace create --resource-group $RG --workspace-name $LAW --output none
}

$LAW_ID  = (Invoke-Az monitor log-analytics workspace show --resource-group $RG --workspace-name $LAW --query customerId -o tsv)
$LAW_KEY = (Invoke-Az monitor log-analytics workspace get-shared-keys --resource-group $RG --workspace-name $LAW --query primarySharedKey -o tsv)

Write-Step "Ensuring Container Apps environment: $ENV_NAME"
$caeExists = az containerapp env show --name $ENV_NAME --resource-group $RG 2>$null
if ($LASTEXITCODE -ne 0) {
    Invoke-Az containerapp env create `
        --name $ENV_NAME `
        --resource-group $RG `
        --location $LOCATION `
        --logs-workspace-id $LAW_ID `
        --logs-workspace-key $LAW_KEY `
        --output none
}

$ACR_SERVER = (Invoke-Az acr show --name $ACR --resource-group $RG --query loginServer -o tsv)
$ENV_DOMAIN = (Invoke-Az containerapp env show --name $ENV_NAME --resource-group $RG --query properties.defaultDomain -o tsv)

if ($InfrastructureOnly) {
    Write-Host ""
    Write-Host "Infrastructure ready." -ForegroundColor Green
    Write-Host "  ACR:              $ACR_SERVER"
    Write-Host "  Environment:      $ENV_NAME"
    Write-Host "  Environment FQDN: $ENV_DOMAIN"
    exit 0
}

# ── Build & push images ───────────────────────────────────────────────────────
if (-not $SkipBuild) {
    $images = @(
        @{ File = "Dockerfile.backend"; Name = "chatwithyourdata-backend" },
        @{ File = "Dockerfile.agent";   Name = "chatwithyourdata-agent" },
        @{ File = "Dockerfile.web";     Name = "chatwithyourdata-web" }
    )

    $hasDocker = $null -ne (Get-Command docker -ErrorAction SilentlyContinue)

    foreach ($img in $images) {
        $fullTag = "$ACR_SERVER/$($img.Name):$TAG"
        if ($hasDocker) {
            Write-Step "Building $($img.Name) (local Docker)"
            Invoke-Az acr login --name $ACR | Out-Null
            docker build -f $img.File -t $fullTag .
            if ($LASTEXITCODE -ne 0) { throw "docker build failed for $($img.File)" }
            Write-Step "Pushing $fullTag"
            docker push $fullTag
            if ($LASTEXITCODE -ne 0) { throw "docker push failed for $fullTag" }
        } else {
            Write-Step "Building $($img.Name) in Azure (az acr build)"
            Invoke-Az acr build `
                --registry $ACR `
                --image "$($img.Name):$TAG" `
                --file $img.File `
                . | Out-Null
        }
    }
}

$IMG_BACKEND = "$ACR_SERVER/chatwithyourdata-backend:$TAG"
$IMG_AGENT   = "$ACR_SERVER/chatwithyourdata-agent:$TAG"
$IMG_WEB     = "$ACR_SERVER/chatwithyourdata-web:$TAG"

$AZURE_ENDPOINT = $cfg.AZURE_OPENAI_ENDPOINT.TrimEnd("/")
$AZURE_KEY      = $cfg.AZURE_OPENAI_API_KEY
$AZURE_DEPLOY   = $cfg.AZURE_OPENAI_DEPLOYMENT_NAME
$AZURE_VER      = if ($cfg.AZURE_API_VERSION) { $cfg.AZURE_API_VERSION } else { "2024-08-01-preview" }
$TAVILY         = $cfg.TAVILY_API_KEY
$AIRTABLE_BASE  = $cfg.AIRTABLE_BASE_ID
$AIRTABLE_TABLE = if ($cfg.AIRTABLE_TABLE) { $cfg.AIRTABLE_TABLE } else { "Table 1" }
$AIRTABLE_TOKEN = $cfg.AIRTABLE_TOKEN
$AGENT_ID       = if ($cfg.NEXT_PUBLIC_LANGGRAPH_AGENT_ID) { $cfg.NEXT_PUBLIC_LANGGRAPH_AGENT_ID } else { "dashboard_agent" }

# ── Deploy backend (internal) ─────────────────────────────────────────────────
Write-Step "Deploying backend ($($cfg.APP_BACKEND))"
Ensure-ContainerApp -Cfg $cfg -Name $cfg.APP_BACKEND -Image $IMG_BACKEND -Port 8001 -Ingress "internal" `
    -Cpu "1.0" -Memory "2.0Gi" `
    -SecretArgs @(
        "airtable-token=$AIRTABLE_TOKEN",
        "azure-api-key=$AZURE_KEY",
        "tavily-key=$TAVILY"
    ) `
    -EnvArgs @(
        "FASTAPI_PORT=8001",
        "AIRTABLE_BASE_ID=$AIRTABLE_BASE",
        "AIRTABLE_TABLE=$AIRTABLE_TABLE",
        "AIRTABLE_TOKEN=secretref:airtable-token",
        "AZURE_API_KEY=secretref:azure-api-key",
        "AZURE_API_BASE=$AZURE_ENDPOINT",
        "AZURE_API_VERSION=$AZURE_VER",
        "AZURE_DEPLOYMENT_NAME=$AZURE_DEPLOY",
        "TAVILY_API_KEY=secretref:tavily-key"
    )

# ── Deploy agent (internal) ───────────────────────────────────────────────────
Write-Step "Deploying agent ($($cfg.APP_AGENT))"
Ensure-ContainerApp -Cfg $cfg -Name $cfg.APP_AGENT -Image $IMG_AGENT -Port 8000 -Ingress "internal" `
    -Cpu "0.5" -Memory "1.0Gi" `
    -SecretArgs @(
        "azure-openai-key=$AZURE_KEY",
        "tavily-key=$TAVILY"
    ) `
    -EnvArgs @(
        "LANGGRAPH_AGENT_PORT=8000",
        "AZURE_OPENAI_ENDPOINT=$AZURE_ENDPOINT",
        "AZURE_OPENAI_API_KEY=secretref:azure-openai-key",
        "AZURE_OPENAI_DEPLOYMENT_NAME=$AZURE_DEPLOY",
        "OPENAI_API_VERSION=$AZURE_VER",
        "TAVILY_API_KEY=secretref:tavily-key"
    )

$BACKEND_URL = "https://$($cfg.APP_BACKEND).internal.$ENV_DOMAIN"
$AGENT_URL   = "https://$($cfg.APP_AGENT).internal.$ENV_DOMAIN/copilotkit"

# ── Deploy web (external) ─────────────────────────────────────────────────────
Write-Step "Deploying web ($($cfg.APP_WEB))"
Ensure-ContainerApp -Cfg $cfg -Name $cfg.APP_WEB -Image $IMG_WEB -Port 3000 -Ingress "external" `
    -Cpu "0.5" -Memory "1.0Gi" `
    -SecretArgs @(
        "azure-api-key=$AZURE_KEY"
    ) `
    -EnvArgs @(
        "NODE_ENV=production",
        "FASTAPI_BASE_URL=$BACKEND_URL",
        "LANGGRAPH_AGENT_URL=$AGENT_URL",
        "NEXT_PUBLIC_LANGGRAPH_AGENT_ID=$AGENT_ID",
        "AZURE_API_KEY=secretref:azure-api-key",
        "AZURE_API_BASE=$AZURE_ENDPOINT",
        "AZURE_API_VERSION=$AZURE_VER",
        "AZURE_DEPLOYMENT_NAME=$AZURE_DEPLOY"
    )

$WEB_FQDN = (Invoke-Az containerapp show --name $cfg.APP_WEB --resource-group $RG --query properties.configuration.ingress.fqdn -o tsv)

Write-Host ""
Write-Host "Deployment complete." -ForegroundColor Green
Write-Host ""
Write-Host "  Public app:  https://$WEB_FQDN"
Write-Host "  Backend:     $BACKEND_URL  (internal)"
Write-Host "  Agent:       $AGENT_URL  (internal)"
Write-Host ""
Write-Host "Verify:"
Write-Host "  curl https://$WEB_FQDN/api/copilotkit"
Write-Host ""
Write-Host "Logs:"
Write-Host "  az containerapp logs show --name $($cfg.APP_WEB) --resource-group $RG --follow"

param(
    [string]$Environment,   # dev | test | prod (optional; defaults to terraform.tfvars)
    [string]$ProjectName    # optional; defaults to terraform.tfvars
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path $PSScriptRoot -Parent
$AwsRegion = if ($env:AWS_REGION) { $env:AWS_REGION } elseif ($env:DEFAULT_AWS_REGION) { $env:DEFAULT_AWS_REGION } else { "eu-west-1" }
$BackendEnv = if ($PSBoundParameters.ContainsKey("Environment") -and $Environment) { $Environment } else { "dev" }

function Assert-LastExitCode {
    param([string]$Step)
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE"
    }
}

$DisplayEnvironment = if ($PSBoundParameters.ContainsKey("Environment")) { $Environment } else { "from tfvars" }
$DisplayProjectName = if ($PSBoundParameters.ContainsKey("ProjectName")) { $ProjectName } else { "from tfvars" }
Write-Host "Deploying $DisplayProjectName to $DisplayEnvironment ..." -ForegroundColor Green

# 1. Terraform init with backend config
Set-Location (Join-Path $ProjectRoot "terraform")
$AwsAccountId = aws sts get-caller-identity --query Account --output text
$StateBucket = "saas-nl2sql-analytics-terraform-state-$AwsAccountId"
$LockTable = "saas-nl2sql-analytics-terraform-locks"

terraform init -input=false `
  -backend-config="bucket=$StateBucket" `
  -backend-config="key=$BackendEnv/terraform.tfstate" `
  -backend-config="region=$AwsRegion" `
  -backend-config="dynamodb_table=$LockTable" `
  -backend-config="encrypt=true"
Assert-LastExitCode "Terraform init"

if (-not $PSBoundParameters.ContainsKey("Environment")) { $Environment = "dev" }

if (-not (terraform workspace list | Select-String $Environment)) {
    terraform workspace new $Environment
} else {
    terraform workspace select $Environment
}

# 2. Ensure ECR repository exists
Write-Host "Ensuring ECR repository..." -ForegroundColor Yellow
$EcrArgs = @(
    "apply",
    "-target=aws_ecr_repository.lambda",
    "-var=region=$AwsRegion",
    "-var-file=terraform.tfvars",
    "-auto-approve"
)
if ($PSBoundParameters.ContainsKey("ProjectName")) {
    $EcrArgs += "-var=project_name=$ProjectName"
}
if ($PSBoundParameters.ContainsKey("Environment")) {
    $EcrArgs += "-var=environment=$Environment"
}
terraform @EcrArgs
Assert-LastExitCode "Terraform apply (ECR)"

$RepoUrl = terraform output -raw lambda_ecr_repo_url
Assert-LastExitCode "Terraform output (ECR)"
$Registry = $RepoUrl.Split("/")[0]
$ImageTag = if ($env:LAMBDA_IMAGE_TAG) { $env:LAMBDA_IMAGE_TAG } else { "latest" }
$ImageRef = "${RepoUrl}:${ImageTag}"

Write-Host "Building and pushing Lambda image..." -ForegroundColor Yellow
$LoginCmd = "aws ecr get-login-password --region $AwsRegion | docker login --username AWS --password-stdin $Registry"
cmd /c $LoginCmd
Assert-LastExitCode "ECR login"
cmd /c "set DOCKER_BUILDKIT=0&& docker build --platform linux/amd64 -t $ImageRef -f `"$($ProjectRoot)\backend\Dockerfile.lambda`" `"$($ProjectRoot)\backend`""
Assert-LastExitCode "Docker build"
docker push $ImageRef
Assert-LastExitCode "Docker push"

# 3. Apply Terraform (full)
Write-Host "Applying Terraform..." -ForegroundColor Yellow
$TerraformArgs = @(
    "apply",
    "-var=region=$AwsRegion",
    "-var=lambda_image_tag=$ImageTag",
    "-var-file=terraform.tfvars",
    "-auto-approve"
)
if ($PSBoundParameters.ContainsKey("ProjectName")) {
    $TerraformArgs += "-var=project_name=$ProjectName"
}
if ($PSBoundParameters.ContainsKey("Environment")) {
    $TerraformArgs += "-var=environment=$Environment"
}
terraform @TerraformArgs
Assert-LastExitCode "Terraform apply"

$ApiUrl = terraform output -raw api_gateway_url
$FrontendBucket = terraform output -raw s3_frontend_bucket
$CloudFrontUrl = terraform output -raw cloudfront_url

# 3. Build + deploy frontend
Set-Location (Join-Path $ProjectRoot "frontend")
Write-Host "Setting API URL for production..." -ForegroundColor Yellow
if (-not $env:NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY) {
    throw "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY is required for the frontend build. Set it in your environment before running deploy."
}
@(
  "NEXT_PUBLIC_BACKEND_URL=$ApiUrl",
  "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=$($env:NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY)"
) | Out-File .env.production -Encoding utf8
$EnvLocalPath = Join-Path (Get-Location) ".env.local"
$EnvLocalBackup = Join-Path (Get-Location) ".env.local.deploy.bak"
if (Test-Path $EnvLocalPath) {
    if (Test-Path $EnvLocalBackup) {
        Remove-Item $EnvLocalBackup -Force
    }
    Move-Item $EnvLocalPath $EnvLocalBackup
}
try {
    npm install
    Assert-LastExitCode "npm install"
    npm run build
    Assert-LastExitCode "npm run build"
    aws s3 sync .\out "s3://$FrontendBucket/" --delete
    Assert-LastExitCode "S3 sync"
} finally {
    if (Test-Path $EnvLocalBackup) {
        Move-Item $EnvLocalBackup $EnvLocalPath
    }
}

# 4. Optional CloudFront invalidation
if ($env:CREATE_INVALIDATION -eq "true") {
    $CfDomain = $CloudFrontUrl -replace "^https://", ""
    $DistributionId = aws cloudfront list-distributions `
        --query "DistributionList.Items[?DomainName=='$CfDomain'].Id | [0]" `
        --output text
    if ($DistributionId -and $DistributionId -ne "None") {
        aws cloudfront create-invalidation --distribution-id $DistributionId --paths "/*"
    } else {
        Write-Host "CloudFront distribution not found for $CfDomain. Skipping invalidation." -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "Deployment complete!" -ForegroundColor Green
Write-Host "CloudFront URL : $CloudFrontUrl" -ForegroundColor Cyan
Write-Host "API Gateway    : $ApiUrl" -ForegroundColor Cyan

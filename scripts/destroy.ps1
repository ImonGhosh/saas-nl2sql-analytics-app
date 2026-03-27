param(
    [string]$Environment,   # dev | test | prod (optional; defaults to terraform.tfvars)
    [string]$ProjectName    # optional; defaults to terraform.tfvars
)

$ErrorActionPreference = "Stop"

$DisplayEnvironment = if ($PSBoundParameters.ContainsKey("Environment")) { $Environment } else { "from tfvars" }
$DisplayProjectName = if ($PSBoundParameters.ContainsKey("ProjectName")) { $ProjectName } else { "from tfvars" }
Write-Host "Preparing to destroy $DisplayProjectName-$DisplayEnvironment infrastructure..." -ForegroundColor Yellow

$ProjectRoot = Split-Path $PSScriptRoot -Parent
$AwsRegion = if ($env:AWS_REGION) { $env:AWS_REGION } elseif ($env:DEFAULT_AWS_REGION) { $env:DEFAULT_AWS_REGION } else { "eu-west-1" }
$BackendEnv = if ($PSBoundParameters.ContainsKey("Environment") -and $Environment) { $Environment } else { "dev" }

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

if (-not $PSBoundParameters.ContainsKey("Environment")) { $Environment = "dev" }

if (-not (terraform workspace list | Select-String $Environment)) {
    Write-Host "Error: Workspace '$Environment' does not exist" -ForegroundColor Red
    terraform workspace list
    exit 1
}

terraform workspace select $Environment

Write-Host "Emptying S3 buckets..." -ForegroundColor Yellow
$FrontendBucket = ""
$MemoryBucket = ""
try {
    $FrontendBucket = terraform output -raw s3_frontend_bucket 2>$null
} catch {
    $FrontendBucket = ""
}
try {
    $MemoryBucket = terraform output -raw s3_memory_bucket 2>$null
} catch {
    $MemoryBucket = ""
}
if (-not $FrontendBucket) {
    $FallbackProject = if ($ProjectName) { $ProjectName } else { "saas-nl2sql-analytics-app" }
    $FrontendBucket = "$FallbackProject-$Environment-frontend-$AwsAccountId"
}
if (-not $MemoryBucket) {
    $FallbackProject = if ($ProjectName) { $ProjectName } else { "saas-nl2sql-analytics-app" }
    $MemoryBucket = "$FallbackProject-$Environment-memory-$AwsAccountId"
}

try {
    aws s3 ls "s3://$FrontendBucket" 2>$null | Out-Null
    aws s3 rm "s3://$FrontendBucket" --recursive
} catch {
    Write-Host "Frontend bucket not found or already empty" -ForegroundColor Gray
}

try {
    aws s3 ls "s3://$MemoryBucket" 2>$null | Out-Null
    aws s3 rm "s3://$MemoryBucket" --recursive
} catch {
    Write-Host "Memory bucket not found or already empty" -ForegroundColor Gray
}

Write-Host "Running terraform destroy..." -ForegroundColor Yellow
$TerraformArgs = @("destroy", "-var=region=$AwsRegion", "-var-file=terraform.tfvars", "-auto-approve")
if ($PSBoundParameters.ContainsKey("ProjectName")) {
    $TerraformArgs += "-var=project_name=$ProjectName"
}
if ($PSBoundParameters.ContainsKey("Environment")) {
    $TerraformArgs += "-var=environment=$Environment"
}
terraform @TerraformArgs

Write-Host "Infrastructure for $Environment has been destroyed!" -ForegroundColor Green
Write-Host ""
Write-Host "  To remove the workspace completely, run:" -ForegroundColor Cyan
Write-Host "   terraform workspace select default" -ForegroundColor White
Write-Host "   terraform workspace delete $Environment" -ForegroundColor White

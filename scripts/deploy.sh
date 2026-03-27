#!/bin/bash
set -euo pipefail

# Optional overrides. If unset, terraform.tfvars provides defaults.
ENVIRONMENT=${1:-}
PROJECT_NAME=${2:-}
AWS_REGION=${AWS_REGION:-${DEFAULT_AWS_REGION:-eu-west-1}}

PROJECT_ROOT=$(cd "$(dirname "$0")/.." && pwd)

DISPLAY_ENVIRONMENT=${ENVIRONMENT:-from tfvars}
DISPLAY_PROJECT=${PROJECT_NAME:-from tfvars}
echo "Deploying ${DISPLAY_PROJECT} to ${DISPLAY_ENVIRONMENT}..."

# 1. Terraform init with backend config
cd "${PROJECT_ROOT}/terraform"
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
STATE_BUCKET="saas-nl2sql-analytics-terraform-state-${AWS_ACCOUNT_ID}"
LOCK_TABLE="saas-nl2sql-analytics-terraform-locks"

terraform init -input=false \
  -backend-config="bucket=${STATE_BUCKET}" \
  -backend-config="key=${ENVIRONMENT:-dev}/terraform.tfstate" \
  -backend-config="region=${AWS_REGION}" \
  -backend-config="dynamodb_table=${LOCK_TABLE}" \
  -backend-config="encrypt=true"

if [ -z "$ENVIRONMENT" ]; then
  ENVIRONMENT="dev"
fi

if ! terraform workspace list | grep -q "$ENVIRONMENT"; then
  terraform workspace new "$ENVIRONMENT"
else
  terraform workspace select "$ENVIRONMENT"
fi

# 2. Ensure ECR repository exists
echo "Ensuring ECR repository..."
ECR_ARGS=(apply -target=aws_ecr_repository.lambda -var="region=${AWS_REGION}" -var-file="terraform.tfvars" -auto-approve)
if [ -n "$PROJECT_NAME" ]; then
  ECR_ARGS+=(-var="project_name=${PROJECT_NAME}")
fi
if [ -n "$ENVIRONMENT" ]; then
  ECR_ARGS+=(-var="environment=${ENVIRONMENT}")
fi
terraform "${ECR_ARGS[@]}"

REPO_URL=$(terraform output -raw lambda_ecr_repo_url)
IMAGE_TAG=${LAMBDA_IMAGE_TAG:-latest}
REGISTRY="${REPO_URL%%/*}"

echo "Building and pushing Lambda image..."
aws ecr get-login-password --region "${AWS_REGION}" | docker login --username AWS --password-stdin "${REGISTRY}"
DOCKER_BUILDKIT=0 docker build --platform linux/amd64 -t "${REPO_URL}:${IMAGE_TAG}" -f "${PROJECT_ROOT}/backend/Dockerfile.lambda" "${PROJECT_ROOT}/backend"
docker push "${REPO_URL}:${IMAGE_TAG}"

# 3. Apply Terraform (full)
echo "Applying Terraform..."
TF_ARGS=(apply -var="region=${AWS_REGION}" -var="lambda_image_tag=${IMAGE_TAG}" -var-file="terraform.tfvars" -auto-approve)
if [ -n "$PROJECT_NAME" ]; then
  TF_ARGS+=(-var="project_name=${PROJECT_NAME}")
fi
if [ -n "$ENVIRONMENT" ]; then
  TF_ARGS+=(-var="environment=${ENVIRONMENT}")
fi
terraform "${TF_ARGS[@]}"

API_URL=$(terraform output -raw api_gateway_url)
FRONTEND_BUCKET=$(terraform output -raw s3_frontend_bucket)
CLOUDFRONT_URL=$(terraform output -raw cloudfront_url)

# 3. Build + deploy frontend
cd "${PROJECT_ROOT}/frontend"
echo "Setting API URL for production..."
if [ -z "${NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY:-}" ]; then
  echo "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY is required for the frontend build. Export it before running deploy."
  exit 1
fi
cat > .env.production <<EOF
NEXT_PUBLIC_BACKEND_URL=${API_URL}
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=${NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY}
EOF
ENV_LOCAL_PATH=".env.local"
ENV_LOCAL_BACKUP=".env.local.deploy.bak"
restore_env_local() {
  if [ -f "$ENV_LOCAL_BACKUP" ]; then
    mv -f "$ENV_LOCAL_BACKUP" "$ENV_LOCAL_PATH"
  fi
}
if [ -f "$ENV_LOCAL_PATH" ]; then
  mv -f "$ENV_LOCAL_PATH" "$ENV_LOCAL_BACKUP"
fi
trap restore_env_local EXIT

npm install
npm run build
aws s3 sync ./out "s3://${FRONTEND_BUCKET}/" --delete

# 4. Optional CloudFront invalidation
if [ "${CREATE_INVALIDATION:-false}" = "true" ]; then
  CF_DOMAIN="${CLOUDFRONT_URL#https://}"
  DIST_ID=$(aws cloudfront list-distributions \
    --query "DistributionList.Items[?DomainName=='${CF_DOMAIN}'].Id | [0]" \
    --output text)
  if [ -n "$DIST_ID" ] && [ "$DIST_ID" != "None" ]; then
    aws cloudfront create-invalidation --distribution-id "$DIST_ID" --paths "/*"
  else
    echo "CloudFront distribution not found for ${CF_DOMAIN}. Skipping invalidation."
  fi
fi

echo ""
echo "Deployment complete!"
echo "CloudFront URL : ${CLOUDFRONT_URL}"
echo "API Gateway    : ${API_URL}"

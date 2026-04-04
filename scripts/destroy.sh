#!/bin/bash
set -euo pipefail

ENVIRONMENT=${1:-}
PROJECT_NAME=${2:-}
AWS_REGION=${AWS_REGION:-${DEFAULT_AWS_REGION:-eu-west-1}}

PROJECT_ROOT=$(cd "$(dirname "$0")/.." && pwd)

DISPLAY_ENVIRONMENT=${ENVIRONMENT:-from tfvars}
DISPLAY_PROJECT=${PROJECT_NAME:-from tfvars}
echo "Preparing to destroy ${DISPLAY_PROJECT}-${DISPLAY_ENVIRONMENT} infrastructure..."

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
  echo "Error: Workspace '$ENVIRONMENT' does not exist"
  terraform workspace list
  exit 1
fi

terraform workspace select "$ENVIRONMENT"

echo "Emptying S3 buckets..."
FRONTEND_BUCKET=$(terraform output -raw s3_frontend_bucket 2>/dev/null || true)
MEMORY_BUCKET=$(terraform output -raw s3_memory_bucket 2>/dev/null || true)
if [ -z "$FRONTEND_BUCKET" ]; then
  FALLBACK_PROJECT=${PROJECT_NAME:-saas-nl2sql-analytics-app}
  FRONTEND_BUCKET="${FALLBACK_PROJECT}-${ENVIRONMENT}-frontend-${AWS_ACCOUNT_ID}"
fi
if [ -z "$MEMORY_BUCKET" ]; then
  FALLBACK_PROJECT=${PROJECT_NAME:-saas-nl2sql-analytics-app}
  MEMORY_BUCKET="${FALLBACK_PROJECT}-${ENVIRONMENT}-memory-${AWS_ACCOUNT_ID}"
fi

if aws s3 ls "s3://${FRONTEND_BUCKET}" >/dev/null 2>&1; then
  aws s3 rm "s3://${FRONTEND_BUCKET}" --recursive
else
  echo "Frontend bucket not found or already empty"
fi

if aws s3 ls "s3://${MEMORY_BUCKET}" >/dev/null 2>&1; then
  aws s3 rm "s3://${MEMORY_BUCKET}" --recursive
else
  echo "Memory bucket not found or already empty"
fi

echo "Running terraform destroy..."
TF_ARGS=(destroy -var="region=${AWS_REGION}" -var-file="terraform.tfvars" -auto-approve)
if [ -n "$PROJECT_NAME" ]; then
  TF_ARGS+=(-var="project_name=${PROJECT_NAME}")
fi
if [ -n "$ENVIRONMENT" ]; then
  TF_ARGS+=(-var="environment=${ENVIRONMENT}")
fi
terraform "${TF_ARGS[@]}"

echo "Infrastructure for ${ENVIRONMENT} has been destroyed."
echo "To remove the workspace completely:"
echo "  terraform workspace select default"
echo "  terraform workspace delete ${ENVIRONMENT}"

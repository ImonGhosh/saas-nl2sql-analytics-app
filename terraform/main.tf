data "aws_caller_identity" "current" {}

locals {
  name_prefix = "${var.project_name}-${var.environment}"

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }

  lambda_env_base = {
    USE_S3                  = "true"
    S3_BUCKET               = aws_s3_bucket.memory.id
    SUPABASE_MCP_REDIRECT_URI = "https://${aws_cloudfront_distribution.main.domain_name}/mcp/callback"
    MCP_METADATA_QUEUE_URL  = aws_sqs_queue.metadata_jobs.url
    MCP_CHART_QUEUE_URL     = aws_sqs_queue.chart_jobs.url
    CORS_ALLOW_ORIGINS      = "https://${aws_cloudfront_distribution.main.domain_name}"
  }

  api_routes = [
    "GET /api",
    "GET /health",
    "POST /mcp/auth/start",
    "POST /mcp/auth/callback",
    "GET /mcp/status",
    "GET /mcp/metadata/status",
    "POST /mcp/metadata/retry",
    "POST /mcp/disconnect",
    "POST /sql/query",
    "GET /sql/conversations",
    "GET /sql/conversations/{session_id}",
    "DELETE /sql/conversations/{session_id}",
    "POST /charts/query",
    "POST /charts/query/async",
    "POST /charts/query/abort",
    "GET /charts/query/status",
    "GET /charts/last",
    "GET /charts/suggestions",
    "GET /charts/library",
    "POST /charts/library",
    "DELETE /charts/library/{saved_at}"
  ]

  secrets_manager_env = var.secrets_manager_arn != "" ? {
    SECRETS_MANAGER_ARN = var.secrets_manager_arn
  } : {}

  secrets_manager_region_env = var.secrets_manager_region != "" ? {
    SECRETS_MANAGER_REGION = var.secrets_manager_region
  } : {}
}

data "aws_ecr_image" "lambda" {
  repository_name = aws_ecr_repository.lambda.name
  image_tag       = var.lambda_image_tag
}

locals {
  lambda_image_uri = "${aws_ecr_repository.lambda.repository_url}@${data.aws_ecr_image.lambda.image_digest}"
}

# S3 bucket for conversation memory (private)
resource "aws_s3_bucket" "memory" {
  bucket = "${local.name_prefix}-memory-${data.aws_caller_identity.current.account_id}"
  tags   = local.tags
}

resource "aws_s3_bucket_public_access_block" "memory" {
  bucket = aws_s3_bucket.memory.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "memory" {
  bucket = aws_s3_bucket.memory.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# S3 bucket for frontend assets (private, served by CloudFront OAC)
resource "aws_s3_bucket" "frontend" {
  bucket = "${local.name_prefix}-frontend-${data.aws_caller_identity.current.account_id}"
  tags   = local.tags
}

resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# SQS queue for metadata extraction jobs
resource "aws_sqs_queue" "metadata_jobs" {
  name                      = "${local.name_prefix}-metadata-jobs"
  visibility_timeout_seconds = var.lambda_timeout + 30
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.metadata_jobs_dlq.arn
    maxReceiveCount     = 3
  })
  tags                      = local.tags
}

# DLQ for metadata jobs
resource "aws_sqs_queue" "metadata_jobs_dlq" {
  name = "${local.name_prefix}-metadata-jobs-dlq"
  tags = local.tags
}

# SQS queue for chart generation jobs
resource "aws_sqs_queue" "chart_jobs" {
  name                      = "${local.name_prefix}-chart-jobs"
  visibility_timeout_seconds = var.lambda_timeout + 30
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.chart_jobs_dlq.arn
    maxReceiveCount     = 3
  })
  tags                      = local.tags
}

# DLQ for chart jobs
resource "aws_sqs_queue" "chart_jobs_dlq" {
  name = "${local.name_prefix}-chart-jobs-dlq"
  tags = local.tags
}

resource "aws_ecr_repository" "lambda" {
  name         = "${local.name_prefix}-lambda"
  force_delete = true
  tags         = local.tags

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_cloudfront_origin_access_control" "frontend" {
  name                              = "${local.name_prefix}-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_function" "rewrite_index" {
  name    = "${local.name_prefix}-rewrite-index"
  runtime = "cloudfront-js-1.0"
  comment = "Rewrite clean URLs to index.html"
  publish = true
  code    = <<EOF
function handler(event) {
  var request = event.request;
  var uri = request.uri;

  if (uri.endsWith('/')) {
    request.uri += 'index.html';
    return request;
  }

  if (!uri.includes('.')) {
    request.uri += '/index.html';
  }

  return request;
}
EOF
}

resource "aws_cloudfront_distribution" "main" {
  enabled             = true
  is_ipv6_enabled     = true
  default_root_object = "index.html"
  tags                = local.tags

  origin {
    domain_name              = aws_s3_bucket.frontend.bucket_regional_domain_name
    origin_id                = "S3-${aws_s3_bucket.frontend.id}"
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend.id

    s3_origin_config {
      origin_access_identity = ""
    }
  }

  default_cache_behavior {
    allowed_methods  = ["GET", "HEAD", "OPTIONS"]
    cached_methods   = ["GET", "HEAD"]
    target_origin_id = "S3-${aws_s3_bucket.frontend.id}"

    forwarded_values {
      query_string = false
      cookies {
        forward = "none"
      }
    }

    viewer_protocol_policy = "redirect-to-https"
    min_ttl                = 0
    default_ttl            = 3600
    max_ttl                = 86400

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.rewrite_index.arn
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  custom_error_response {
    error_code         = 403
    response_code      = 200
    response_page_path = "/index.html"
  }

  custom_error_response {
    error_code         = 404
    response_code      = 200
    response_page_path = "/index.html"
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

# Frontend S3 bucket policy document
data "aws_iam_policy_document" "frontend_bucket_policy" {
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.frontend.arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.main.arn]
    }
  }
}

# Add above policy to Frontend S3 bucket
resource "aws_s3_bucket_policy" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  policy = data.aws_iam_policy_document.frontend_bucket_policy.json
}

# IAM role for Lambda
resource "aws_iam_role" "lambda_role" {
  name = "${local.name_prefix}-lambda-role"
  tags = local.tags

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# IAM role for metadata worker Lambda
resource "aws_iam_role" "worker_role" {
  name = "${local.name_prefix}-worker-role"
  tags = local.tags

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "worker_basic" {
  role       = aws_iam_role.worker_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Create a policy document to use the memory S3 bucket and AWS Secrets
data "aws_iam_policy_document" "lambda_inline" {
  statement {
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:ListBucket"
    ]
    resources = [
      aws_s3_bucket.memory.arn,
      "${aws_s3_bucket.memory.arn}/*"
    ]
  }

  statement {
    actions   = ["sqs:SendMessage"]
    resources = [
      aws_sqs_queue.metadata_jobs.arn,
      aws_sqs_queue.chart_jobs.arn
    ]
  }

  dynamic "statement" {
    for_each = var.secrets_manager_arn != "" ? [var.secrets_manager_arn] : []
    content {
      actions   = ["secretsmanager:GetSecretValue"]
      resources = [statement.value]
    }
  }
}

# Add above policy to Lambda role so that Lambda has access to S3 bucket and AWS Secrets
resource "aws_iam_role_policy" "lambda_inline" {
  name   = "${local.name_prefix}-lambda-inline"
  role   = aws_iam_role.lambda_role.id
  policy = data.aws_iam_policy_document.lambda_inline.json
}

# Worker policy for S3, Secrets Manager, and SQS receive
data "aws_iam_policy_document" "worker_inline" {
  statement {
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:ListBucket"
    ]
    resources = [
      aws_s3_bucket.memory.arn,
      "${aws_s3_bucket.memory.arn}/*"
    ]
  }

  statement {
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes"
    ]
    resources = [
      aws_sqs_queue.metadata_jobs.arn,
      aws_sqs_queue.chart_jobs.arn
    ]
  }

  dynamic "statement" {
    for_each = var.secrets_manager_arn != "" ? [var.secrets_manager_arn] : []
    content {
      actions   = ["secretsmanager:GetSecretValue"]
      resources = [statement.value]
    }
  }
}

resource "aws_iam_role_policy" "worker_inline" {
  name   = "${local.name_prefix}-worker-inline"
  role   = aws_iam_role.worker_role.id
  policy = data.aws_iam_policy_document.worker_inline.json
}

# Main Lambda function
resource "aws_lambda_function" "api" {
  function_name    = "${local.name_prefix}-api"
  role             = aws_iam_role.lambda_role.arn # Add the lambda role to this Lambda function
  package_type     = "Image"
  image_uri        = local.lambda_image_uri
  timeout          = var.lambda_timeout
  memory_size      = var.lambda_memory_size
  tags             = local.tags

  environment {
    variables = merge(
      local.lambda_env_base,
      local.secrets_manager_env,
      local.secrets_manager_region_env,
      var.lambda_env
    )
  }
}

# Worker Lambda function (SQS-triggered)
resource "aws_lambda_function" "worker" {
  function_name    = "${local.name_prefix}-metadata-worker"
  role             = aws_iam_role.worker_role.arn
  package_type     = "Image"
  image_uri        = local.lambda_image_uri
  timeout          = var.lambda_timeout
  memory_size      = var.lambda_memory_size
  tags             = local.tags

  image_config {
    command = ["metadata_worker_handler.handler"]
  }

  environment {
    variables = merge(
      local.lambda_env_base,
      local.secrets_manager_env,
      local.secrets_manager_region_env,
      var.lambda_env
    )
  }
}

# Chart worker Lambda function (SQS-triggered)
resource "aws_lambda_function" "chart_worker" {
  function_name    = "${local.name_prefix}-chart-worker"
  role             = aws_iam_role.worker_role.arn
  package_type     = "Image"
  image_uri        = local.lambda_image_uri
  timeout          = var.lambda_timeout
  memory_size      = var.lambda_memory_size
  tags             = local.tags

  image_config {
    command = ["chart_worker_handler.handler"]
  }

  environment {
    variables = merge(
      local.lambda_env_base,
      local.secrets_manager_env,
      local.secrets_manager_region_env,
      var.lambda_env
    )
  }
}

# SQS -> worker Lambda event source mapping
resource "aws_lambda_event_source_mapping" "metadata_jobs" {
  event_source_arn = aws_sqs_queue.metadata_jobs.arn
  function_name    = aws_lambda_function.worker.arn
  batch_size       = 1
  enabled          = true
}

# SQS -> chart worker Lambda event source mapping
resource "aws_lambda_event_source_mapping" "chart_jobs" {
  event_source_arn = aws_sqs_queue.chart_jobs.arn
  function_name    = aws_lambda_function.chart_worker.arn
  batch_size       = 1
  enabled          = true
}
# API Gateway HTTP API
resource "aws_apigatewayv2_api" "main" {
  name          = "${local.name_prefix}-api-gateway"
  protocol_type = "HTTP"
  tags          = local.tags

  cors_configuration {
    allow_credentials = false
    allow_headers     = [
      "authorization",
      "content-type",
      "x-api-key",
      "x-amz-date",
      "x-amz-security-token"
    ]
    allow_methods     = ["GET", "POST", "OPTIONS", "PUT", "PATCH", "DELETE"]
    allow_origins     = ["https://${aws_cloudfront_distribution.main.domain_name}"]
    max_age           = 600
  }
}

# Connect API Gateway to AWS Lambda Function
resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api.invoke_arn
  payload_format_version = "2.0"
}

# Add a catch-all route instead of specific routes (i.e all paths are handled by same Lambda)
resource "aws_apigatewayv2_route" "explicit" {
  for_each  = toset(local.api_routes)
  api_id    = aws_apigatewayv2_api.main.id
  route_key = each.value
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

# Additional API Gateway configurations
resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.main.id
  name        = "$default"
  auto_deploy = true
  tags        = local.tags

  default_route_settings {
    throttling_burst_limit = var.api_throttle_burst_limit
    throttling_rate_limit  = var.api_throttle_rate_limit
  }
}

# Allow API Gateway to invoke Lambda
resource "aws_lambda_permission" "api_gw" {
  statement_id  = "AllowExecutionFromAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}

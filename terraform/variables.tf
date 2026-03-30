variable "project_name" {
  description = "Name prefix for all resources."
  type        = string
  validation {
    condition     = can(regex("^[a-z0-9-]+$", var.project_name))
    error_message = "project_name must contain only lowercase letters, numbers, and hyphens."
  }
}

variable "environment" {
  description = "Environment name (dev, test, prod)."
  type        = string
  validation {
    condition     = contains(["dev", "test", "prod"], var.environment)
    error_message = "environment must be one of: dev, test, prod."
  }
}

variable "region" {
  description = "AWS region for Lambda/API/S3."
  type        = string
  default     = "eu-west-1"
}

variable "lambda_timeout" {
  description = "Lambda function timeout in seconds."
  type        = number
  default     = 300
}

variable "lambda_memory_size" {
  description = "Lambda function memory in MB."
  type        = number
  default     = 512
}

variable "lambda_image_tag" {
  description = "Docker image tag for the Lambda container image."
  type        = string
  default     = "latest"
}

variable "api_throttle_burst_limit" {
  description = "API Gateway throttle burst limit."
  type        = number
  default     = 10
}

variable "api_throttle_rate_limit" {
  description = "API Gateway throttle rate limit."
  type        = number
  default     = 5
}

variable "secrets_manager_arn" {
  description = "Secrets Manager ARN holding backend secrets JSON."
  type        = string
  default     = ""
}

variable "secrets_manager_region" {
  description = "Optional Secrets Manager region override."
  type        = string
  default     = ""
}

variable "lambda_env" {
  description = "Additional Lambda environment variables (avoid secrets if using Secrets Manager)."
  type        = map(string)
  default     = {}
  sensitive   = true
}

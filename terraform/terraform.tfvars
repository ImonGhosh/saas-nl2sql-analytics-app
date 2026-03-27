project_name = "saas-nl2sql-analytics-app"
environment  = "dev"
secrets_manager_arn = "arn:aws:secretsmanager:eu-west-1:453229563925:secret:saas-nl2sql-analytics-app-secrets-h5BrS9"
lambda_env = {
  METADATA_CACHE_TTL_SECONDS = "3600"
  SQL_AGENT_MODEL            = "gpt-5-mini"
  CHART_QUERY_MODEL          = "gpt-5-mini"
  CHART_SPEC_MODEL           = "gpt-5-mini"
  CHART_SUGGESTIONS_MODEL    = "gpt-5-mini"
}

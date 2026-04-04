terraform {
  backend "s3" {
    # These values will be set by deployment scripts
    # They can be passed via -backend-config
  }
}

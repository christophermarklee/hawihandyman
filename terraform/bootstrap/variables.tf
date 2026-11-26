variable "aws_region" {
  description = "AWS Region for the application and Terraform state."
  type        = string
  default     = "us-east-2"
}

variable "github_owner" {
  description = "GitHub repository owner permitted to deploy."
  type        = string
  default     = "christophermarklee"
}

variable "github_repository" {
  description = "GitHub repository permitted to deploy."
  type        = string
  default     = "hawihandyman"
}

variable "github_owner_id" {
  description = "Immutable GitHub numeric owner ID used by the OIDC subject."
  type        = string
  default     = "32991873"
}

variable "github_repository_id" {
  description = "Immutable GitHub numeric repository ID used by the OIDC subject."
  type        = string
  default     = "1473585456"
}

variable "github_branch" {
  description = "Branch permitted to assume the deployment role."
  type        = string
  default     = "main"
}

variable "hosted_zone_id" {
  description = "Route 53 public hosted zone ID for hawihandyman.com."
  type        = string
  default     = "Z08420312N3V2BJTSCR9O"
}

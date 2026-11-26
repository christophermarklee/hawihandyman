variable "aws_region" {
  description = "AWS Region hosting the site."
  type        = string
  default     = "us-east-2"
}

variable "aws_account_id" {
  description = "AWS account ID containing the ECR image repository."
  type        = string
}

variable "image_tag" {
  description = "Immutable Git commit SHA tag of the image to deploy."
  type        = string
}

variable "hosted_zone_id" {
  description = "Route 53 public hosted zone ID for hawihandyman.com."
  type        = string
  default     = "Z08420312N3V2BJTSCR9O"
}

variable "certbot_email" {
  description = "Email Certbot uses for certificate expiry and account notices."
  type        = string
  default     = "christopher@agilityqa.com"
}

variable "vpc_cidr" {
  description = "CIDR block for the public ECS networking VPC."
  type        = string
  default     = "10.42.0.0/16"
}

variable "haleclock_admin_password" {
  description = "Password for the HaleClock admin login."
  type        = string
  sensitive   = true
}

variable "haleclock_secret_key" {
  description = "Secret key signing HaleClock session cookies."
  type        = string
  sensitive   = true
}

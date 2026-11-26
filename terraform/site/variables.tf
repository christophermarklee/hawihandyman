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

variable "ses_from_address" {
  description = "Verified customer email sender address on hawihandyman.com."
  type        = string
  default     = "bookings@hawihandyman.com"
}

variable "ses_reply_to_address" {
  description = "Optional reply-to address for customer email."
  type        = string
  default     = ""
}

variable "google_client_id" {
  description = "Google OAuth client ID for Cognito federation; leave empty to disable Google sign-in."
  type        = string
  sensitive   = true
  default     = ""
}

variable "google_client_secret" {
  description = "Google OAuth client secret for Cognito federation."
  type        = string
  sensitive   = true
  default     = ""
}

variable "facebook_app_id" {
  description = "Facebook app ID for Cognito federation; leave empty to disable Facebook sign-in."
  type        = string
  sensitive   = true
  default     = ""
}

variable "facebook_app_secret" {
  description = "Facebook app secret for Cognito federation."
  type        = string
  sensitive   = true
  default     = ""
}

variable "apple_service_id" {
  description = "Apple Services ID for Cognito federation; leave empty to disable Apple sign-in."
  type        = string
  sensitive   = true
  default     = ""
}

variable "apple_team_id" {
  description = "Apple Developer Team ID."
  type        = string
  sensitive   = true
  default     = ""
}

variable "apple_key_id" {
  description = "Apple Sign in with Apple key ID."
  type        = string
  sensitive   = true
  default     = ""
}

variable "apple_private_key" {
  description = "Contents of the Apple Sign in with Apple .p8 private key."
  type        = string
  sensitive   = true
  default     = ""
}

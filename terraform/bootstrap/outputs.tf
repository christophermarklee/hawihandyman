output "state_bucket_name" {
  description = "Use this value as the GitHub Actions TF_STATE_BUCKET variable."
  value       = aws_s3_bucket.terraform_state.bucket
}

output "ecr_repository_url" {
  description = "ECR repository receiving GitHub-built site images."
  value       = aws_ecr_repository.site.repository_url
}

output "github_deploy_role_arn" {
  description = "Use this value as the GitHub Actions AWS_ROLE_ARN variable."
  value       = aws_iam_role.github_deploy.arn
}

output "aws_account_id" {
  description = "Use this value as the GitHub Actions AWS_ACCOUNT_ID variable."
  value       = data.aws_caller_identity.current.account_id
}

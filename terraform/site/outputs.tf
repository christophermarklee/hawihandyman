output "cognito_customer_user_pool_id" {
  description = "Cognito user pool for customer accounts."
  value       = aws_cognito_user_pool.customers.id
}

output "cognito_customer_app_client_id" {
  description = "Public OAuth app client ID for the customer web app."
  value       = aws_cognito_user_pool_client.customers.id
}

output "cognito_customer_domain" {
  description = "Managed login domain for customer accounts."
  value       = "https://${aws_cognito_user_pool_domain.customers.domain}.auth.${var.aws_region}.amazoncognito.com"
}

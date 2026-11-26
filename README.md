# Hawi Handyman

This repository builds and deploys a Fedora 45 Apache site to Amazon ECS/Fargate.
GitHub Actions uses OIDC for short-lived AWS credentials. Terraform state is
stored in an encrypted, versioned S3 bucket with native S3 lock files.

## One-time AWS bootstrap

Use an AWS CLI profile with permission to create the bootstrap resources. The
Agent Toolkit profile configured for this workspace is named `hawihandyman`.

```sh
export AWS_PROFILE=hawihandyman
terraform -chdir=terraform/bootstrap init
terraform -chdir=terraform/bootstrap apply
```

The bootstrap creates:

- The private, versioned S3 Terraform state bucket.
- The immutable-tagged ECR repository used by GitHub Actions.
- The GitHub Actions OIDC provider and a deployment role restricted to this
  repository's `main` branch.

Set the repository Actions variables from the bootstrap outputs. These commands
require an authenticated GitHub CLI (`gh auth login`):

```sh
gh variable set AWS_ROLE_ARN --body "$(terraform -chdir=terraform/bootstrap output -raw github_deploy_role_arn)"
gh variable set AWS_REGION --body "us-east-2"
gh variable set AWS_ACCOUNT_ID --body "$(terraform -chdir=terraform/bootstrap output -raw aws_account_id)"
gh variable set TF_STATE_BUCKET --body "$(terraform -chdir=terraform/bootstrap output -raw state_bucket_name)"
```

## Deploy

Push a change to `main` (or run the **Build and deploy** workflow manually).
GitHub Actions builds an immutable image tagged with the commit SHA and
workflow run ID, pushes it to ECR, then applies `terraform/site`. Replace the
starter page in `site/` with the website content before deploying.

The site stack creates a public VPC, an internet-facing Network Load Balancer,
one Fargate task, and an encrypted EFS access point for persistent Certbot
certificates. TCP 443 passes through the load balancer so Apache terminates
HTTPS inside the container. Certbot uses Route 53 DNS validation for
`hawihandyman.com` and `www.hawihandyman.com`; its contact address is
`christopher@agilityqa.com`. Terraform creates the corresponding Route 53 A
aliases in hosted zone `Z08420312N3V2BJTSCR9O`.

Fargate is configured with one task to avoid duplicate certificate issuance and
keep the initial deployment simple. The Network Load Balancer forwards traffic
across Availability Zones to that task. This is not a multi-task highly
available configuration.

## Local checks

```sh
docker build -t hawihandyman:local .
terraform -chdir=terraform/bootstrap init
terraform -chdir=terraform/bootstrap validate
terraform -chdir=terraform/site init -backend=false
terraform -chdir=terraform/site validate
```

The bootstrap state is local; keep its `terraform.tfstate` private and backed
up. The site state is remote and uses S3 native locking.

## Cost and security notes

AWS charges for the Fargate task, Network Load Balancer and its load-balancer
capacity, public IPv4 addresses, EFS storage/throughput, CloudWatch Logs, ECR
storage, and Route 53 queries. EFS is retained to preserve the ACME account and
certificate during task replacement. The task role can change only the
ACME-validation TXT records in the configured hosted zone; the GitHub OIDC
trust is limited to pushes from this repository's `main` branch. Review AWS
pricing and the generated Terraform plan before applying.

Do not commit `.env`, AWS credentials, Terraform state, or Terraform plans.
After creating the site stack, destroy `terraform/site` before removing the
bootstrap resources if you want to tear down the deployment.

For stronger audit visibility, enable CloudTrail S3 data events and S3 request
metrics for the state bucket, and server access logging to a separate encrypted
logging bucket. These account-level logging resources are intentionally not
created by this minimal bootstrap.
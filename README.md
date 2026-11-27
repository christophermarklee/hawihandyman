# Hawi Handyman

This repository builds and deploys the Hawi Handyman website and **HaleClock**
— a self-hosted scheduling, time-tracking, and cash-invoicing app — as a single
Fedora 45 Apache + FastAPI container on Amazon ECS/Fargate.
GitHub Actions uses OIDC for short-lived AWS credentials. Terraform state is
stored in an encrypted, versioned S3 bucket with native S3 lock files.

## HaleClock

The FastAPI app in `app/` runs on `127.0.0.1:8000` inside the container; Apache
serves the static landing page from `site/` at `/` and reverse-proxies these
paths to the app:

- `/book` — public client self-booking (service block → open slot → details),
  with travel-buffer and double-booking protection (`BEGIN IMMEDIATE`).
- `/i/{token}` — public shareable invoice links with a PAID stamp.
- `/app` — Google SSO-protected mobile-first admin app: Today (one-tap clock in /
  break / clock out with live earnings), Schedule, Timecards (manual entry and edits),
  and Invoices (built from timecards + materials with Hawaii GET). Services and
  Settings are available from the app header.
- `/api` — availability and booking endpoints used by the booking page.

All timestamps are stored as UTC in SQLite and rendered in the configured
timezone (default `Pacific/Honolulu`). The database lives at
`/var/lib/haleclock/haleclock.db` on a dedicated EFS access point, so it
survives task replacement. WAL mode is deliberately not used because the
database sits on NFS; the deployment is single-task/single-writer.

### Local development

```sh
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python -r requirements.txt pytest httpx
HALECLOCK_DB=/tmp/haleclock.db \
HALECLOCK_SECRET_KEY=dev-secret \
HALECLOCK_ADMIN_EMAILS=allinsheds@gmail.com,christopher@agilityqa.com \
.venv/bin/uvicorn app.main:app --reload
```

In another terminal:

```sh
.venv/bin/python -m pytest tests/
```

### Required GitHub Actions secrets

```sh
openssl rand -base64 48 | gh secret set HALECLOCK_SECRET_KEY
```

Terraform stores the session key in an SSM SecureString parameter, and the ECS
task reads it as a container secret. Terraform state also contains its
configured value; keep the encrypted S3 site state and any Terraform plans
private.

Admin access uses Google sign-in through Cognito and is restricted to
`allinsheds@gmail.com` and `christopher@agilityqa.com`. The admin app requires
the Google provider to be enabled; there is no password-login fallback.

### Customer accounts

`/account` uses an Amazon Cognito User Pool for email/password sign-up and
sign-in. Customers can review their appointments and invoices, book new work
while signed in, or claim an existing booking with its confirmation code.
Guest booking remains available. A booking is the initial project record;
multiple visits per project can be modeled separately if that workflow is
needed later.

The site stack provisions a Cognito managed-login domain and public OAuth app
client. The app uses authorization-code flow with PKCE and stores only the
local customer-account ID in its signed session, not Cognito tokens. The
Cognito `sub` is the stable identity key; account history is never linked
automatically by matching an email address or phone number.

Social providers are enabled when their credentials are set as GitHub Actions
secrets:

- Google: `COGNITO_GOOGLE_CLIENT_ID`, `COGNITO_GOOGLE_CLIENT_SECRET`
- Facebook: `COGNITO_FACEBOOK_APP_ID`, `COGNITO_FACEBOOK_APP_SECRET`
- Apple: `COGNITO_APPLE_SERVICE_ID`, `COGNITO_APPLE_TEAM_ID`,
  `COGNITO_APPLE_KEY_ID`, `COGNITO_APPLE_PRIVATE_KEY`

Create the OAuth applications with each provider and register Cognito's
`/oauth2/idpresponse` callback URL with them. Apple requires a Services ID and
Sign in with Apple key; provide the `.p8` key contents as the Actions secret.
The deployment workflow passes these credentials to Terraform, so the
encrypted remote Terraform state contains their values. Restrict state-bucket
access and never put provider credentials in source control or Terraform plans
that are shared.

### Customer email

Amazon SES sends booking confirmations, appointment changes, invoice notices,
and Cognito account verification emails from `bookings@hawihandyman.com`.
Terraform creates the SES domain identity, DKIM records, and a custom MAIL FROM
domain at `mail.hawihandyman.com`, plus a DMARC policy starting at `p=none`;
the task uses its IAM role to send email without stored AWS credentials.
Optionally set the GitHub Actions variable
`SES_REPLY_TO_ADDRESS` if customer replies should go to a different address.

New SES accounts can be restricted to verified recipients until production
sending access is approved. The Terraform deployment does not request that
account-level access automatically.

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
workflow run ID, runs the app tests, pushes the image to ECR, then applies
`terraform/site`. Before the first deploy of HaleClock or customer accounts,
add the required HaleClock Actions secrets and re-apply `terraform/bootstrap`
so its deployment role can manage the app's SSM parameters, Cognito user pool,
SES identity, and SES DNS records.

The site stack creates a public VPC, an internet-facing Network Load Balancer,
one Fargate task, and encrypted EFS access points for persistent Certbot
certificates and the HaleClock SQLite database. TCP 443 passes through the load
balancer so Apache terminates HTTPS inside the container. Certbot uses Route 53
DNS validation for
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
data "aws_caller_identity" "current" {}
data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  name               = "hawihandyman"
  availability_zones = slice(data.aws_availability_zones.available.names, 0, 2)
  subnet_cidrs       = [for index in range(2) : cidrsubnet(var.vpc_cidr, 8, index)]
  ecr_repository_url = "${var.aws_account_id}.dkr.ecr.${var.aws_region}.amazonaws.com/${local.name}"
  efs_arn            = aws_efs_file_system.certificates.arn
  access_point_arns  = [aws_efs_access_point.certificates.arn, aws_efs_access_point.haleclock_data.arn]
  hosted_zone_arn    = "arn:aws:route53:::hostedzone/${var.hosted_zone_id}"
}

resource "aws_vpc" "site" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true
}

resource "aws_internet_gateway" "site" {
  vpc_id = aws_vpc.site.id
}

resource "aws_subnet" "public" {
  count = 2

  vpc_id                  = aws_vpc.site.id
  cidr_block              = local.subnet_cidrs[count.index]
  availability_zone       = local.availability_zones[count.index]
  map_public_ip_on_launch = true
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.site.id
}

resource "aws_route" "internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.site.id
}

resource "aws_route_table_association" "public" {
  count = 2

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_security_group" "load_balancer" {
  name        = "${local.name}-nlb"
  description = "Public HTTP and HTTPS entry points."
  vpc_id      = aws_vpc.site.id

  ingress {
    protocol    = "tcp"
    from_port   = 80
    to_port     = 80
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    protocol    = "tcp"
    from_port   = 443
    to_port     = 443
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "tasks" {
  name        = "${local.name}-tasks"
  description = "Allow web traffic only from the network load balancer."
  vpc_id      = aws_vpc.site.id

  ingress {
    protocol        = "tcp"
    from_port       = 80
    to_port         = 80
    security_groups = [aws_security_group.load_balancer.id]
  }

  ingress {
    protocol        = "tcp"
    from_port       = 443
    to_port         = 443
    security_groups = [aws_security_group.load_balancer.id]
  }

  egress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "efs" {
  name        = "${local.name}-efs"
  description = "Allow NFS from ECS tasks."
  vpc_id      = aws_vpc.site.id

  ingress {
    protocol        = "tcp"
    from_port       = 2049
    to_port         = 2049
    security_groups = [aws_security_group.tasks.id]
  }
}

resource "aws_efs_file_system" "certificates" {
  encrypted        = true
  performance_mode = "generalPurpose"
  throughput_mode  = "elastic"
}

resource "aws_efs_access_point" "certificates" {
  file_system_id = aws_efs_file_system.certificates.id

  posix_user {
    uid = 0
    gid = 0
  }

  root_directory {
    path = "/letsencrypt"
    creation_info {
      owner_uid   = 0
      owner_gid   = 0
      permissions = "0700"
    }
  }
}

resource "aws_efs_access_point" "haleclock_data" {
  file_system_id = aws_efs_file_system.certificates.id

  posix_user {
    uid = 0
    gid = 0
  }

  root_directory {
    path = "/haleclock"
    creation_info {
      owner_uid   = 0
      owner_gid   = 0
      permissions = "0700"
    }
  }
}

resource "aws_efs_file_system_policy" "certificates" {
  file_system_id = aws_efs_file_system.certificates.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        AWS = aws_iam_role.task.arn
      }
      Action = [
        "elasticfilesystem:ClientMount",
        "elasticfilesystem:ClientWrite",
        "elasticfilesystem:ClientRootAccess"
      ]
      Resource = local.efs_arn
      Condition = {
        Bool = {
          "aws:SecureTransport" = "true"
        }
        StringEquals = {
          "elasticfilesystem:AccessPointArn" = local.access_point_arns
        }
      }
    }]
  })
}

resource "aws_efs_mount_target" "public" {
  count = 2

  file_system_id  = aws_efs_file_system.certificates.id
  subnet_id       = aws_subnet.public[count.index].id
  security_groups = [aws_security_group.efs.id]
}

resource "aws_lb" "site" {
  name                             = "${local.name}-nlb"
  internal                         = false
  load_balancer_type               = "network"
  subnets                          = aws_subnet.public[*].id
  security_groups                  = [aws_security_group.load_balancer.id]
  enable_cross_zone_load_balancing = true
}

resource "aws_lb_target_group" "http" {
  name        = "${local.name}-http"
  port        = 80
  protocol    = "TCP"
  target_type = "ip"
  vpc_id      = aws_vpc.site.id

  health_check {
    protocol = "TCP"
    port     = "traffic-port"
  }
}

resource "aws_lb_target_group" "https" {
  name        = "${local.name}-https"
  port        = 443
  protocol    = "TCP"
  target_type = "ip"
  vpc_id      = aws_vpc.site.id

  health_check {
    protocol = "TCP"
    port     = "traffic-port"
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.site.arn
  port              = 80
  protocol          = "TCP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.http.arn
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.site.arn
  port              = 443
  protocol          = "TCP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.https.arn
  }
}

resource "aws_cloudwatch_log_group" "site" {
  name              = "/ecs/${local.name}"
  retention_in_days = 30
}

resource "aws_iam_role" "execution" {
  name = "${local.name}-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
      Action = "sts:AssumeRole"
      Condition = {
        StringEquals = {
          "aws:SourceAccount" = data.aws_caller_identity.current.account_id
        }
        ArnLike = {
          "aws:SourceArn" = "arn:aws:ecs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_ssm_parameter" "haleclock_admin_password" {
  name  = "/${local.name}/haleclock/admin-password"
  type  = "SecureString"
  value = var.haleclock_admin_password
}

resource "aws_ssm_parameter" "haleclock_secret_key" {
  name  = "/${local.name}/haleclock/secret-key"
  type  = "SecureString"
  value = var.haleclock_secret_key
}

resource "aws_iam_role_policy" "execution_secrets" {
  name = "${local.name}-execution-secrets"
  role = aws_iam_role.execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "ReadHaleClockSecrets"
      Effect = "Allow"
      Action = ["ssm:GetParameters"]
      Resource = [
        aws_ssm_parameter.haleclock_admin_password.arn,
        aws_ssm_parameter.haleclock_secret_key.arn
      ]
    }]
  })
}

resource "aws_iam_role" "task" {
  name = "${local.name}-task"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
      Action = "sts:AssumeRole"
      Condition = {
        StringEquals = {
          "aws:SourceAccount" = data.aws_caller_identity.current.account_id
        }
        ArnLike = {
          "aws:SourceArn" = "arn:aws:ecs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "task" {
  name = "${local.name}-task-access"
  role = aws_iam_role.task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "MountPersistentCertificates"
        Effect   = "Allow"
        Action   = ["elasticfilesystem:ClientMount", "elasticfilesystem:ClientWrite", "elasticfilesystem:ClientRootAccess"]
        Resource = local.efs_arn
        Condition = {
          Bool = {
            "aws:SecureTransport" = "true"
          }
          StringEquals = {
            "elasticfilesystem:AccessPointArn" = local.access_point_arns
          }
        }
      },
      {
        Sid      = "DiscoverCertbotHostedZone"
        Effect   = "Allow"
        Action   = ["route53:ListHostedZones"]
        Resource = "*"
      },
      {
        Sid      = "ChangeOnlyAcmeTxtRecords"
        Effect   = "Allow"
        Action   = ["route53:ChangeResourceRecordSets"]
        Resource = local.hosted_zone_arn
        Condition = {
          "ForAllValues:StringLike" = {
            "route53:ChangeResourceRecordSetsNormalizedRecordNames" = [
              "_acme-challenge.hawihandyman.com",
              "_acme-challenge.www.hawihandyman.com"
            ]
          }
          "ForAllValues:StringEquals" = {
            "route53:ChangeResourceRecordSetsRecordTypes" = ["TXT"]
          }
          Null = {
            "route53:ChangeResourceRecordSetsNormalizedRecordNames" = "false"
            "route53:ChangeResourceRecordSetsRecordTypes"           = "false"
          }
        }
      },
      {
        Sid      = "PollDnsChanges"
        Effect   = "Allow"
        Action   = ["route53:GetChange"]
        Resource = "arn:aws:route53:::change/*"
      }
    ]
  })
}

resource "aws_ecs_cluster" "site" {
  name = local.name
}

resource "aws_ecs_task_definition" "site" {
  family                   = local.name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  volume {
    name = "letsencrypt"
    efs_volume_configuration {
      file_system_id     = aws_efs_file_system.certificates.id
      transit_encryption = "ENABLED"
      authorization_config {
        access_point_id = aws_efs_access_point.certificates.id
        iam             = "ENABLED"
      }
    }
  }

  volume {
    name = "haleclock-data"
    efs_volume_configuration {
      file_system_id     = aws_efs_file_system.certificates.id
      transit_encryption = "ENABLED"
      authorization_config {
        access_point_id = aws_efs_access_point.haleclock_data.id
        iam             = "ENABLED"
      }
    }
  }

  container_definitions = jsonencode([{
    name      = local.name
    image     = "${local.ecr_repository_url}:${var.image_tag}"
    essential = true
    user      = "0"
    portMappings = [
      { containerPort = 80, protocol = "tcp" },
      { containerPort = 443, protocol = "tcp" }
    ]
    environment = [
      { name = "CERTBOT_EMAIL", value = var.certbot_email },
      { name = "HALECLOCK_DB", value = "/var/lib/haleclock/haleclock.db" }
    ]
    secrets = [
      {
        name      = "HALECLOCK_ADMIN_PASSWORD"
        valueFrom = aws_ssm_parameter.haleclock_admin_password.arn
      },
      {
        name      = "HALECLOCK_SECRET_KEY"
        valueFrom = aws_ssm_parameter.haleclock_secret_key.arn
      }
    ]
    mountPoints = [
      {
        sourceVolume  = "letsencrypt"
        containerPath = "/etc/letsencrypt"
        readOnly      = false
      },
      {
        sourceVolume  = "haleclock-data"
        containerPath = "/var/lib/haleclock"
        readOnly      = false
      }
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.site.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "ecs"
      }
    }
  }])
}

resource "aws_ecs_service" "site" {
  name                              = local.name
  cluster                           = aws_ecs_cluster.site.id
  task_definition                   = aws_ecs_task_definition.site.arn
  desired_count                     = 1
  launch_type                       = "FARGATE"
  platform_version                  = "LATEST"
  health_check_grace_period_seconds = 900
  wait_for_steady_state             = true

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.http.arn
    container_name   = local.name
    container_port   = 80
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.https.arn
    container_name   = local.name
    container_port   = 443
  }

  depends_on = [
    aws_efs_mount_target.public,
    aws_efs_file_system_policy.certificates,
    aws_iam_role_policy_attachment.execution,
    aws_iam_role_policy.task,
    aws_lb_listener.http,
    aws_lb_listener.https
  ]
}

resource "aws_route53_record" "apex" {
  zone_id = var.hosted_zone_id
  name    = "hawihandyman.com"
  type    = "A"

  alias {
    name                   = aws_lb.site.dns_name
    zone_id                = aws_lb.site.zone_id
    evaluate_target_health = true
  }
}

resource "aws_route53_record" "www" {
  zone_id = var.hosted_zone_id
  name    = "www.hawihandyman.com"
  type    = "A"

  alias {
    name                   = aws_lb.site.dns_name
    zone_id                = aws_lb.site.zone_id
    evaluate_target_health = true
  }
}

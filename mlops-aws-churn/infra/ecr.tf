resource "aws_ecr_repository" "mlops_repo" {
  name                 = "${var.project_name}-training"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
  }
}

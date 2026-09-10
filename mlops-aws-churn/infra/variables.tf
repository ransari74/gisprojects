variable "project_name" {
  description = "Base name used to derive resource names"
  type        = string
  default     = "mlops-churn"
}

variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment tag (dev/staging/prod)"
  type        = string
  default     = "dev"
}

output "bucket_name" {
  value = aws_s3_bucket.mlops_bucket.bucket
}

output "sagemaker_execution_role_arn" {
  value = aws_iam_role.sagemaker_execution_role.arn
}

output "github_actions_ci_role_arn" {
  value = aws_iam_role.github_actions_ci_role.arn
}

output "ecr_repository_url" {
  value = aws_ecr_repository.mlops_repo.repository_url
}

output "model_package_group_name" {
  value = aws_sagemaker_model_package_group.churn_models.model_package_group_name
}

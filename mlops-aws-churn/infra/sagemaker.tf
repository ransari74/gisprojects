resource "aws_sagemaker_model_package_group" "churn_models" {
  model_package_group_name        = "${var.project_name}-models"
  model_package_group_description = "Registered churn-prediction candidates (baseline, XGBoost, LightGBM, PyTorch NN)"
}

"""Register a trained model artifact as a SageMaker Model Package in the
`mlops-churn-models` Model Package Group (created by Terraform), pending
manual approval before deployment.

Requires live AWS credentials with SageMaker permissions — not runnable
without them, included so the registration step is fully specified.
"""
import argparse

import boto3


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-package-group", default="mlops-churn-models")
    parser.add_argument("--model-artifact-s3-uri", required=True,
                         help="s3://bucket/path/model.tar.gz")
    parser.add_argument("--image-uri", required=True,
                         help="Inference container image URI (e.g. SageMaker XGBoost built-in image)")
    parser.add_argument("--auc", type=float, required=True)
    parser.add_argument("--f1", type=float, required=True)
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args()

    sm_client = boto3.client("sagemaker", region_name=args.region)

    response = sm_client.create_model_package(
        ModelPackageGroupName=args.model_package_group,
        ModelPackageDescription=f"AUC={args.auc:.4f} F1={args.f1:.4f}",
        InferenceSpecification={
            "Containers": [{"Image": args.image_uri, "ModelDataUrl": args.model_artifact_s3_uri}],
            "SupportedContentTypes": ["text/csv"],
            "SupportedResponseMIMETypes": ["text/csv"],
        },
        ModelApprovalStatus="PendingManualApproval",
        CustomerMetadataProperties={"val_auc": str(args.auc), "val_f1": str(args.f1)},
    )
    print(f"Created model package: {response['ModelPackageArn']}")


if __name__ == "__main__":
    main()

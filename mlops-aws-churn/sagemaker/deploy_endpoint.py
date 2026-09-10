"""Deploy an approved SageMaker Model Package to a real-time endpoint.

Requires live AWS credentials — not runnable without them, included so the
deployment step is fully specified end-to-end.
"""
import argparse

import boto3


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-package-arn", required=True)
    parser.add_argument("--endpoint-name", default="churn-endpoint")
    parser.add_argument("--instance-type", default="ml.m5.large")
    parser.add_argument("--instance-count", type=int, default=1)
    parser.add_argument("--role-arn", required=True)
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args()

    sm_client = boto3.client("sagemaker", region_name=args.region)

    model_name = f"{args.endpoint_name}-model"
    sm_client.create_model(
        ModelName=model_name,
        Containers=[{"ModelPackageName": args.model_package_arn}],
        ExecutionRoleArn=args.role_arn,
    )

    config_name = f"{args.endpoint_name}-config"
    sm_client.create_endpoint_config(
        EndpointConfigName=config_name,
        ProductionVariants=[{
            "VariantName": "AllTraffic",
            "ModelName": model_name,
            "InstanceType": args.instance_type,
            "InitialInstanceCount": args.instance_count,
        }],
    )

    existing = sm_client.list_endpoints(NameContains=args.endpoint_name)["Endpoints"]
    if any(e["EndpointName"] == args.endpoint_name for e in existing):
        sm_client.update_endpoint(EndpointName=args.endpoint_name, EndpointConfigName=config_name)
        print(f"Updating existing endpoint: {args.endpoint_name}")
    else:
        sm_client.create_endpoint(EndpointName=args.endpoint_name, EndpointConfigName=config_name)
        print(f"Creating new endpoint: {args.endpoint_name}")


if __name__ == "__main__":
    main()

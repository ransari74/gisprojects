"""Register the winning MLflow run's model into the Azure ML Model Registry.

Requires an authenticated Azure ML workspace context (az login + a
configured resource group/workspace, or AZURE_* env vars for
DefaultAzureCredential). Not runnable without live Azure credentials —
included so the registration step is fully specified end-to-end.
"""
import argparse

from azure.ai.ml import MLClient
from azure.ai.ml.entities import Model
from azure.ai.ml.constants import AssetTypes
from azure.identity import DefaultAzureCredential


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True, help="Azure ML / MLflow run ID of the winning model")
    parser.add_argument("--model-name", default="eurosat-landcover")
    parser.add_argument("--subscription-id", default=None, help="defaults to az CLI context")
    parser.add_argument("--resource-group", default=None, help="defaults to az CLI context")
    parser.add_argument("--workspace-name", default=None, help="defaults to az CLI context")
    parser.add_argument("--description", default="EuroSAT land-cover classifier")
    args = parser.parse_args()

    credential = DefaultAzureCredential()
    ml_client = MLClient(
        credential,
        subscription_id=args.subscription_id,
        resource_group_name=args.resource_group,
        workspace_name=args.workspace_name,
    )

    model = Model(
        path=f"azureml://jobs/{args.run_id}/outputs/artifacts/paths/model/",
        name=args.model_name,
        description=args.description,
        type=AssetTypes.MLFLOW_MODEL,
    )
    registered = ml_client.models.create_or_update(model)
    print(f"Registered model {registered.name} version {registered.version}")


if __name__ == "__main__":
    main()

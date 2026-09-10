"""SageMaker Pipelines definition: preprocess -> train (baseline, XGBoost
with HPO tuning, LightGBM, PyTorch NN) -> evaluate -> register.

Requires live AWS credentials + a SageMaker execution role. Not runnable
without them from this environment; run with --submit --execute against a
real AWS account to actually create/execute the pipeline.
"""
import argparse

import sagemaker
from sagemaker.estimator import Estimator
from sagemaker.parameter import ContinuousParameter, IntegerParameter
from sagemaker.processing import ProcessingInput, ProcessingOutput, ScriptProcessor
from sagemaker.pytorch import PyTorch
from sagemaker.sklearn.estimator import SKLearn
from sagemaker.tuner import HyperparameterTuner
from sagemaker.workflow.condition_step import ConditionStep
from sagemaker.workflow.conditions import ConditionGreaterThanOrEqualTo
from sagemaker.workflow.parameters import ParameterFloat, ParameterString
from sagemaker.workflow.pipeline import Pipeline
from sagemaker.workflow.properties import PropertyFile
from sagemaker.workflow.steps import ProcessingStep, TrainingStep, TuningStep
from sagemaker.xgboost.estimator import XGBoost

PIPELINE_DESCRIPTION = (
    "Churn prediction: preprocess -> {baseline, xgboost (+HPO), lightgbm, "
    "pytorch NN} -> evaluate -> conditionally register best model"
)


def build_pipeline(role_arn: str, bucket: str, pipeline_name: str, source_dir: str = "..") -> Pipeline:
    session = sagemaker.Session(default_bucket=bucket)
    base_job_prefix = "mlops-churn"

    min_auc_param = ParameterFloat(name="MinAUCThreshold", default_value=0.75)
    instance_type_param = ParameterString(name="TrainingInstanceType", default_value="ml.m5.xlarge")

    preprocess_processor = ScriptProcessor(
        image_uri=sagemaker.image_uris.retrieve("sklearn", session.boto_region_name, version="1.2-1"),
        command=["python3"],
        instance_type="ml.m5.large",
        instance_count=1,
        role=role_arn,
        sagemaker_session=session,
        base_job_name=f"{base_job_prefix}-preprocess",
    )
    preprocess_step = ProcessingStep(
        name="PreprocessChurnData",
        processor=preprocess_processor,
        inputs=[ProcessingInput(source=f"s3://{bucket}/raw", destination="/opt/ml/processing/input")],
        outputs=[
            ProcessingOutput(output_name="train", source="/opt/ml/processing/train"),
            ProcessingOutput(output_name="val", source="/opt/ml/processing/val"),
            ProcessingOutput(output_name="test", source="/opt/ml/processing/test"),
        ],
        code=f"{source_dir}/src/data/preprocess.py",
    )

    train_data = preprocess_step.properties.ProcessingOutputConfig.Outputs["train"].S3Output.S3Uri
    val_data = preprocess_step.properties.ProcessingOutputConfig.Outputs["val"].S3Output.S3Uri

    # --- Candidate 1: baseline logistic regression (SKLearn estimator) ---
    baseline_estimator = SKLearn(
        entry_point="src/models/baseline.py",
        source_dir=source_dir,
        role=role_arn,
        instance_type=instance_type_param,
        instance_count=1,
        framework_version="1.2-1",
        base_job_name=f"{base_job_prefix}-baseline",
        sagemaker_session=session,
    )
    baseline_step = TrainingStep(
        name="TrainBaseline",
        estimator=baseline_estimator,
        inputs={"train": train_data, "val": val_data},
    )

    # --- Candidate 2: XGBoost + Automatic Model Tuning ---
    xgb_estimator = XGBoost(
        entry_point="src/models/train_xgboost.py",
        source_dir=source_dir,
        role=role_arn,
        instance_type=instance_type_param,
        instance_count=1,
        framework_version="1.7-1",
        base_job_name=f"{base_job_prefix}-xgboost",
        sagemaker_session=session,
    )
    tuner = HyperparameterTuner(
        estimator=xgb_estimator,
        objective_metric_name="validation:auc",
        objective_type="Maximize",
        metric_definitions=[{"Name": "validation:auc", "Regex": r"validation:auc=([0-9.]+)"}],
        hyperparameter_ranges={
            "max-depth": IntegerParameter(3, 10),
            "learning-rate": ContinuousParameter(0.01, 0.3),
            "n-estimators": IntegerParameter(100, 500),
        },
        max_jobs=20,
        max_parallel_jobs=4,
        base_tuning_job_name=f"{base_job_prefix}-xgb-tune",
    )
    xgb_tuning_step = TuningStep(
        name="TuneXGBoost",
        tuner=tuner,
        inputs={"train": train_data, "val": val_data},
    )

    # --- Candidate 3: LightGBM ---
    lgbm_estimator = SKLearn(
        entry_point="src/models/train_lightgbm.py",
        source_dir=source_dir,
        role=role_arn,
        instance_type=instance_type_param,
        instance_count=1,
        framework_version="1.2-1",
        base_job_name=f"{base_job_prefix}-lightgbm",
        sagemaker_session=session,
    )
    lgbm_step = TrainingStep(
        name="TrainLightGBM",
        estimator=lgbm_estimator,
        inputs={"train": train_data, "val": val_data},
    )

    # --- Candidate 4: PyTorch feed-forward NN ---
    nn_estimator = PyTorch(
        entry_point="src/models/train_nn.py",
        source_dir=source_dir,
        role=role_arn,
        instance_type=instance_type_param,
        instance_count=1,
        framework_version="2.2",
        py_version="py310",
        base_job_name=f"{base_job_prefix}-nn",
        sagemaker_session=session,
    )
    nn_step = TrainingStep(
        name="TrainPyTorchNN",
        estimator=nn_estimator,
        inputs={"train": train_data, "val": val_data},
    )

    # --- Evaluate all four and conditionally register the best ---
    evaluate_processor = ScriptProcessor(
        image_uri=sagemaker.image_uris.retrieve("sklearn", session.boto_region_name, version="1.2-1"),
        command=["python3"],
        instance_type="ml.m5.large",
        instance_count=1,
        role=role_arn,
        sagemaker_session=session,
        base_job_name=f"{base_job_prefix}-evaluate",
    )
    evaluation_report = PropertyFile(
        name="EvaluationReport", output_name="evaluation", path="evaluation.json",
    )
    evaluate_step = ProcessingStep(
        name="EvaluateCandidates",
        processor=evaluate_processor,
        inputs=[
            ProcessingInput(source=baseline_step.properties.ModelArtifacts.S3ModelArtifacts,
                             destination="/opt/ml/processing/models/baseline"),
            ProcessingInput(source=xgb_tuning_step.get_top_model_s3_uri(top_k=0, s3_bucket=bucket),
                             destination="/opt/ml/processing/models/xgboost"),
            ProcessingInput(source=lgbm_step.properties.ModelArtifacts.S3ModelArtifacts,
                             destination="/opt/ml/processing/models/lightgbm"),
            ProcessingInput(source=nn_step.properties.ModelArtifacts.S3ModelArtifacts,
                             destination="/opt/ml/processing/models/pytorch_nn"),
        ],
        outputs=[ProcessingOutput(output_name="evaluation", source="/opt/ml/processing/evaluation")],
        code=f"{source_dir}/src/evaluate.py",
        property_files=[evaluation_report],
    )

    register_condition = ConditionGreaterThanOrEqualTo(
        left=evaluate_step.properties.ProcessingOutputConfig.Outputs["evaluation"].S3Output.S3Uri,
        right=min_auc_param,
    )
    condition_step = ConditionStep(
        name="CheckAUCThreshold",
        conditions=[register_condition],
        if_steps=[],   # registration performed by src/registry.py, invoked separately after approval
        else_steps=[],
    )

    pipeline = Pipeline(
        name=pipeline_name,
        parameters=[min_auc_param, instance_type_param],
        steps=[preprocess_step, baseline_step, xgb_tuning_step, lgbm_step, nn_step, evaluate_step, condition_step],
        sagemaker_session=session,
    )
    return pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role-arn", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--pipeline-name", default="mlops-churn-pipeline")
    parser.add_argument("--submit", action="store_true", help="upsert the pipeline definition")
    parser.add_argument("--execute", action="store_true", help="start a pipeline execution after submitting")
    args = parser.parse_args()

    pipeline = build_pipeline(args.role_arn, args.bucket, args.pipeline_name)

    if args.submit:
        pipeline.upsert(role_arn=args.role_arn, description=PIPELINE_DESCRIPTION)
        print(f"Upserted pipeline: {args.pipeline_name}")

    if args.execute:
        execution = pipeline.start()
        print(f"Started execution: {execution.arn}")


if __name__ == "__main__":
    main()

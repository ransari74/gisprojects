"""Lightweight experiment tracking: logs to SageMaker Experiments when
running inside a SageMaker training job, otherwise falls back to a local
JSON file so results can be compared without any AWS resources.
"""
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def _in_sagemaker() -> bool:
    return "SM_TRAINING_ENV" in os.environ


@contextmanager
def run(run_name: str, params: dict, local_dir: Path = Path("./experiments")):
    record = {
        "run_name": run_name,
        "params": params,
        "metrics": {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    sm_run = None
    if _in_sagemaker():
        try:
            from sagemaker.experiments.run import Run
            sm_run = Run(experiment_name="mlops-churn", run_name=run_name)
            sm_run.__enter__()
            sm_run.log_parameters(params)
        except Exception as exc:  # noqa: BLE001 - tracking must never break training
            print(f"SageMaker Experiments unavailable ({exc}); using local JSON logging.")
            sm_run = None

    def log_metrics(metrics: dict, step: int = None):
        record["metrics"].update(metrics)
        if sm_run is not None:
            for key, value in metrics.items():
                sm_run.log_metric(name=key, value=value, step=step)
        else:
            print(f"[{run_name}] " + " ".join(f"{k}={v:.4f}" for k, v in metrics.items()))

    try:
        yield log_metrics
    finally:
        if sm_run is not None:
            sm_run.__exit__(None, None, None)
        else:
            local_dir.mkdir(parents=True, exist_ok=True)
            out_path = local_dir / f"{run_name}.json"
            with open(out_path, "w") as f:
                json.dump(record, f, indent=2)
            print(f"Wrote local experiment record to {out_path}")

"""Train an XGBoost churn classifier. Hyperparameters here are the
SageMaker-tuning-job defaults (configs/train_config.yaml); when run inside
a SageMaker HPO trial, SM_HP_* env vars (set by the tuning job) override
them via argparse defaults sourced from the environment.
"""
import argparse
import os
from pathlib import Path

import pandas as pd
import xgboost as xgb
import yaml
from sklearn.metrics import f1_score, roc_auc_score

from src.data.preprocess import build_feature_matrix
from src.tracking import run as tracking_run

CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "train_config.yaml"


def _env_default(name: str, cfg_value):
    return type(cfg_value)(os.environ.get(f"SM_HP_{name}", cfg_value))


def main() -> None:
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    target = cfg["data"]["target_column"]
    xgb_cfg = cfg["xgboost"]

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("./data/processed"))
    parser.add_argument("--n-estimators", type=int, default=_env_default("n_estimators", xgb_cfg["n_estimators"]))
    parser.add_argument("--max-depth", type=int, default=_env_default("max_depth", xgb_cfg["max_depth"]))
    parser.add_argument("--learning-rate", type=float, default=_env_default("learning_rate", xgb_cfg["learning_rate"]))
    parser.add_argument("--subsample", type=float, default=xgb_cfg["subsample"])
    parser.add_argument("--colsample-bytree", type=float, default=xgb_cfg["colsample_bytree"])
    args = parser.parse_args()

    train_df = pd.read_parquet(args.data_dir / "train.parquet")
    val_df = pd.read_parquet(args.data_dir / "val.parquet")

    X_train, encoder, scaler = build_feature_matrix(train_df, fit=True)
    X_val, _, _ = build_feature_matrix(val_df, fit=False, encoder=encoder, scaler=scaler)

    params = {
        "n_estimators": args.n_estimators,
        "max_depth": args.max_depth,
        "learning_rate": args.learning_rate,
        "subsample": args.subsample,
        "colsample_bytree": args.colsample_bytree,
    }

    with tracking_run("xgboost", params) as log_metrics:
        model = xgb.XGBClassifier(
            **params,
            objective="binary:logistic",
            eval_metric="auc",
        )
        model.fit(
            X_train, train_df[target],
            eval_set=[(X_val, val_df[target])],
            verbose=False,
        )

        val_probs = model.predict_proba(X_val)[:, 1]
        val_preds = (val_probs >= 0.5).astype(int)

        auc = roc_auc_score(val_df[target], val_probs)
        f1 = f1_score(val_df[target], val_preds)
        # SageMaker HPO regex-matches this exact line from stdout for its objective metric.
        print(f"validation:auc={auc:.6f}")
        log_metrics({"val_auc": auc, "val_f1": f1})


if __name__ == "__main__":
    main()

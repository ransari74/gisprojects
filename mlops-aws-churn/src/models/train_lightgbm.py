"""Train a LightGBM churn classifier (second candidate architecture)."""
import argparse
from pathlib import Path

import lightgbm as lgb
import pandas as pd
import yaml
from sklearn.metrics import f1_score, roc_auc_score

from src.data.preprocess import build_feature_matrix
from src.tracking import run as tracking_run

CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "train_config.yaml"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("./data/processed"))
    args = parser.parse_args()

    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    target = cfg["data"]["target_column"]
    params = cfg["lightgbm"]

    train_df = pd.read_parquet(args.data_dir / "train.parquet")
    val_df = pd.read_parquet(args.data_dir / "val.parquet")

    X_train, encoder, scaler = build_feature_matrix(train_df, fit=True)
    X_val, _, _ = build_feature_matrix(val_df, fit=False, encoder=encoder, scaler=scaler)

    with tracking_run("lightgbm", params) as log_metrics:
        model = lgb.LGBMClassifier(
            n_estimators=params["n_estimators"],
            num_leaves=params["num_leaves"],
            learning_rate=params["learning_rate"],
        )
        model.fit(X_train, train_df[target])

        val_probs = model.predict_proba(X_val)[:, 1]
        val_preds = (val_probs >= 0.5).astype(int)

        auc = roc_auc_score(val_df[target], val_probs)
        f1 = f1_score(val_df[target], val_preds)
        log_metrics({"val_auc": auc, "val_f1": f1})


if __name__ == "__main__":
    main()

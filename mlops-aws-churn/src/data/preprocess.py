"""Clean the raw churn CSV, engineer features, and write train/val/test
splits as parquet files ready for model training.
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from src.data.download_data import CATEGORICAL_COLUMNS, NUMERIC_COLUMNS

CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "train_config.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def clean(df: pd.DataFrame, target_column: str) -> pd.DataFrame:
    df = df.copy()
    # TotalCharges arrives as a string in the real dataset with blanks for
    # brand-new customers; coerce and impute with 0 (equivalent to tenure=0).
    df["TotalCharges"] = pd.to_numeric(df["TotalCharges"], errors="coerce").fillna(0.0)
    df[target_column] = (df[target_column] == "Yes").astype(int)
    return df


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["avg_monthly_spend"] = df["TotalCharges"] / df["tenure"].replace(0, 1)
    df["is_new_customer"] = (df["tenure"] <= 3).astype(int)
    return df


def build_feature_matrix(df: pd.DataFrame, fit: bool, encoder=None, scaler=None):
    numeric_cols = NUMERIC_COLUMNS + ["avg_monthly_spend", "is_new_customer"]

    if fit:
        encoder = OneHotEncoder(handle_unknown="ignore", sparse_output=False)
        scaler = StandardScaler()
        cat_features = encoder.fit_transform(df[CATEGORICAL_COLUMNS])
        num_features = scaler.fit_transform(df[numeric_cols])
    else:
        cat_features = encoder.transform(df[CATEGORICAL_COLUMNS])
        num_features = scaler.transform(df[numeric_cols])

    X = np.concatenate([num_features, cat_features], axis=1)
    return X, encoder, scaler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("./data"))
    parser.add_argument("--output-dir", type=Path, default=Path("./data/processed"))
    args = parser.parse_args()

    cfg = load_config()["data"]
    raw_path = args.input_dir / "telco_churn.csv"
    df = pd.read_csv(raw_path)

    df = clean(df, cfg["target_column"])
    df = engineer_features(df)

    train_val, test = train_test_split(
        df, test_size=cfg["split"]["test"], random_state=cfg["split"]["seed"],
        stratify=df[cfg["target_column"]],
    )
    val_ratio = cfg["split"]["val"] / (cfg["split"]["train"] + cfg["split"]["val"])
    train, val = train_test_split(
        train_val, test_size=val_ratio, random_state=cfg["split"]["seed"],
        stratify=train_val[cfg["target_column"]],
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, split_df in [("train", train), ("val", val), ("test", test)]:
        out_path = args.output_dir / f"{name}.parquet"
        split_df.to_parquet(out_path, index=False)
        print(f"{name}: {len(split_df)} rows -> {out_path}")


if __name__ == "__main__":
    main()

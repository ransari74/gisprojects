"""Download the IBM Telco Customer Churn dataset. Falls back to a synthetic
dataset with the same schema when offline, so the pipeline is runnable
without network access (clearly labeled in the output so nobody mistakes it
for real data).
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yaml

CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "train_config.yaml"

CATEGORICAL_COLUMNS = [
    "gender", "Partner", "Dependents", "PhoneService", "MultipleLines",
    "InternetService", "OnlineSecurity", "OnlineBackup", "DeviceProtection",
    "TechSupport", "StreamingTV", "StreamingMovies", "Contract",
    "PaperlessBilling", "PaymentMethod",
]
NUMERIC_COLUMNS = ["tenure", "MonthlyCharges", "TotalCharges", "SeniorCitizen"]


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def download_real_data(url: str) -> pd.DataFrame:
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    from io import StringIO
    return pd.read_csv(StringIO(response.text))


def make_synthetic_data(n_samples: int, seed: int) -> pd.DataFrame:
    """Schema-compatible synthetic fallback. NOT real customer data —
    generated only so the pipeline runs end-to-end without network access.
    """
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({
        "customerID": [f"SYN-{i:05d}" for i in range(n_samples)],
        "gender": rng.choice(["Male", "Female"], n_samples),
        "SeniorCitizen": rng.choice([0, 1], n_samples, p=[0.84, 0.16]),
        "Partner": rng.choice(["Yes", "No"], n_samples),
        "Dependents": rng.choice(["Yes", "No"], n_samples),
        "tenure": rng.integers(0, 73, n_samples),
        "PhoneService": rng.choice(["Yes", "No"], n_samples, p=[0.9, 0.1]),
        "MultipleLines": rng.choice(["Yes", "No", "No phone service"], n_samples),
        "InternetService": rng.choice(["DSL", "Fiber optic", "No"], n_samples),
        "OnlineSecurity": rng.choice(["Yes", "No", "No internet service"], n_samples),
        "OnlineBackup": rng.choice(["Yes", "No", "No internet service"], n_samples),
        "DeviceProtection": rng.choice(["Yes", "No", "No internet service"], n_samples),
        "TechSupport": rng.choice(["Yes", "No", "No internet service"], n_samples),
        "StreamingTV": rng.choice(["Yes", "No", "No internet service"], n_samples),
        "StreamingMovies": rng.choice(["Yes", "No", "No internet service"], n_samples),
        "Contract": rng.choice(["Month-to-month", "One year", "Two year"], n_samples),
        "PaperlessBilling": rng.choice(["Yes", "No"], n_samples),
        "PaymentMethod": rng.choice(
            ["Electronic check", "Mailed check", "Bank transfer (automatic)", "Credit card (automatic)"],
            n_samples,
        ),
        "MonthlyCharges": rng.uniform(18, 120, n_samples).round(2),
    })
    df["TotalCharges"] = (df["MonthlyCharges"] * df["tenure"] + rng.normal(0, 20, n_samples)).clip(lower=0).round(2)

    # Churn probability driven loosely by tenure/contract, so the label carries signal.
    churn_score = (
        -0.05 * df["tenure"]
        + 0.02 * df["MonthlyCharges"]
        + (df["Contract"] == "Month-to-month").astype(float) * 2.0
        + rng.normal(0, 1, n_samples)
    )
    churn_prob = 1 / (1 + np.exp(-(-2 + 0.15 * churn_score)))
    df["Churn"] = np.where(rng.uniform(0, 1, n_samples) < churn_prob, "Yes", "No")
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("./data"))
    parser.add_argument("--force-synthetic", action="store_true")
    args = parser.parse_args()

    cfg = load_config()["data"]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.output_dir / "telco_churn.csv"

    if args.force_synthetic:
        df = make_synthetic_data(**cfg["synthetic_fallback"])
        print("Using synthetic data (--force-synthetic).")
    else:
        try:
            df = download_real_data(cfg["source_url"])
            print(f"Downloaded real dataset: {len(df)} rows from {cfg['source_url']}")
        except Exception as exc:  # noqa: BLE001 - deliberate broad fallback for network issues
            print(f"Download failed ({exc}); falling back to SYNTHETIC data.")
            df = make_synthetic_data(**cfg["synthetic_fallback"])

    df.to_csv(out_path, index=False)
    print(f"Wrote {len(df)} rows to {out_path}")


if __name__ == "__main__":
    main()

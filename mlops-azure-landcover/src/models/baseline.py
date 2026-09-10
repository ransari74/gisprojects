"""Baseline model: multinomial logistic regression on flattened, downsampled
pixel values. This is intentionally weak — it exists to give fine-tuned
models a floor to beat, not to be competitive.
"""
import argparse
from pathlib import Path

import mlflow
import numpy as np
import torch
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score

from src.data.dataset import EuroSATSplit, build_transforms


def flatten_split(data_dir: Path, split: str, image_size: int = 32):
    transform = build_transforms(image_size=image_size, train=False)
    ds = EuroSATSplit(data_dir, split, transform=transform)
    X, y = [], []
    for image, label in ds:
        X.append(image.numpy().flatten())
        y.append(label)
    return np.stack(X), np.array(y)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("./data"))
    parser.add_argument("--epochs", type=int, default=10, help="max_iter for LogisticRegression")
    parser.add_argument("--image-size", type=int, default=32)
    args = parser.parse_args()

    if not mlflow.get_tracking_uri() or mlflow.get_tracking_uri().startswith("file:"):
        mlflow.set_tracking_uri("file:./mlruns")
    mlflow.set_experiment("eurosat-landcover")

    with mlflow.start_run(run_name="baseline-logreg"):
        mlflow.log_params({
            "model": "logistic_regression",
            "image_size": args.image_size,
            "max_iter": args.epochs * 20,
        })

        X_train, y_train = flatten_split(args.data_dir, "train", args.image_size)
        X_val, y_val = flatten_split(args.data_dir, "val", args.image_size)

        clf = LogisticRegression(max_iter=args.epochs * 20)
        clf.fit(X_train, y_train)

        preds = clf.predict(X_val)
        acc = accuracy_score(y_val, preds)
        f1 = f1_score(y_val, preds, average="macro")

        mlflow.log_metrics({"val_accuracy": acc, "val_f1_macro": f1})
        print(f"Baseline LogReg — val_accuracy={acc:.4f} val_f1_macro={f1:.4f}")


if __name__ == "__main__":
    main()

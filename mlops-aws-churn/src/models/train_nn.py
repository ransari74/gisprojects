"""Train a small PyTorch feed-forward NN churn classifier (third candidate
architecture). Written as a SageMaker script-mode entrypoint: reads
SM_CHANNEL_TRAIN/SM_CHANNEL_VAL when present, falls back to --data-dir for
local runs.
"""
import argparse
import json
import os
from pathlib import Path

import pandas as pd
import torch
import torch.nn as nn
import yaml
from sklearn.metrics import f1_score, roc_auc_score
from torch.utils.data import DataLoader, TensorDataset

from src.data.preprocess import build_feature_matrix
from src.tracking import run as tracking_run

CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "train_config.yaml"


class ChurnNet(nn.Module):
    def __init__(self, input_dim: int, hidden_dims: list, dropout: float):
        super().__init__()
        layers = []
        prev_dim = input_dim
        for hidden_dim in hidden_dims:
            layers += [nn.Linear(prev_dim, hidden_dim), nn.ReLU(), nn.Dropout(dropout)]
            prev_dim = hidden_dim
        layers.append(nn.Linear(prev_dim, 1))
        self.net = nn.Sequential(*layers)

    def forward(self, x):
        return self.net(x).squeeze(-1)


def main() -> None:
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    target = cfg["data"]["target_column"]
    nn_cfg = cfg["nn"]

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path,
                         default=Path(os.environ.get("SM_CHANNEL_TRAIN", "./data/processed")))
    parser.add_argument("--epochs", type=int, default=nn_cfg["epochs"])
    parser.add_argument("--batch-size", type=int, default=nn_cfg["batch_size"])
    parser.add_argument("--lr", type=float, default=nn_cfg["lr"])
    args = parser.parse_args()

    train_df = pd.read_parquet(args.data_dir / "train.parquet")
    val_df = pd.read_parquet(args.data_dir / "val.parquet")

    X_train, encoder, scaler = build_feature_matrix(train_df, fit=True)
    X_val, _, _ = build_feature_matrix(val_df, fit=False, encoder=encoder, scaler=scaler)

    train_ds = TensorDataset(torch.tensor(X_train, dtype=torch.float32),
                              torch.tensor(train_df[target].values, dtype=torch.float32))
    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True)

    X_val_t = torch.tensor(X_val, dtype=torch.float32)
    y_val_t = torch.tensor(val_df[target].values, dtype=torch.float32)

    model = ChurnNet(input_dim=X_train.shape[1], hidden_dims=nn_cfg["hidden_dims"], dropout=nn_cfg["dropout"])
    criterion = nn.BCEWithLogitsLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)

    params = {"epochs": args.epochs, "batch_size": args.batch_size, "lr": args.lr,
              "hidden_dims": nn_cfg["hidden_dims"], "dropout": nn_cfg["dropout"]}

    with tracking_run("pytorch-nn", params) as log_metrics:
        best_auc = -1.0
        for epoch in range(args.epochs):
            model.train()
            for xb, yb in train_loader:
                optimizer.zero_grad()
                loss = criterion(model(xb), yb)
                loss.backward()
                optimizer.step()

            model.eval()
            with torch.no_grad():
                val_logits = model(X_val_t)
                val_probs = torch.sigmoid(val_logits).numpy()
            val_preds = (val_probs >= 0.5).astype(int)
            auc = roc_auc_score(val_df[target], val_probs)
            f1 = f1_score(val_df[target], val_preds)
            best_auc = max(best_auc, auc)
            log_metrics({"val_auc": auc, "val_f1": f1}, step=epoch)

        log_metrics({"best_val_auc": best_auc})

    model_dir = Path(os.environ.get("SM_MODEL_DIR", "./outputs"))
    model_dir.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), model_dir / "churn_nn.pt")
    with open(model_dir / "model_metadata.json", "w") as f:
        json.dump({
            "input_dim": X_train.shape[1],
            "hidden_dims": nn_cfg["hidden_dims"],
            "dropout": nn_cfg["dropout"],
        }, f)


if __name__ == "__main__":
    main()

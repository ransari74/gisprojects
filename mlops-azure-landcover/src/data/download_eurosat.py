"""Download the EuroSAT (RGB) dataset and materialize a reproducible
train/val/test split as an index CSV, so every training script reads
identical splits regardless of run order or machine.
"""
import argparse
import csv
import random
from pathlib import Path

import yaml
from torchvision.datasets import EuroSAT

CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "data_config.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def build_splits(data_dir: Path, cfg: dict) -> None:
    dataset = EuroSAT(root=str(data_dir), download=True)
    class_names = dataset.classes
    samples = dataset._samples if hasattr(dataset, "_samples") else dataset.samples

    rng = random.Random(cfg["split"]["seed"])
    indices = list(range(len(samples)))
    rng.shuffle(indices)

    n = len(indices)
    n_train = int(n * cfg["split"]["train"])
    n_val = int(n * cfg["split"]["val"])

    split_assignment = {}
    for i, idx in enumerate(indices):
        if i < n_train:
            split_assignment[idx] = "train"
        elif i < n_train + n_val:
            split_assignment[idx] = "val"
        else:
            split_assignment[idx] = "test"

    out_path = data_dir / "splits.csv"
    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["path", "label", "class_name", "split"])
        for idx, (path, label) in enumerate(samples):
            writer.writerow([path, label, class_names[label], split_assignment[idx]])

    print(f"Wrote {n} rows ({n_train} train / {n_val} val / {n - n_train - n_val} test) to {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("./data"))
    args = parser.parse_args()

    args.data_dir.mkdir(parents=True, exist_ok=True)
    cfg = load_config()
    build_splits(args.data_dir, cfg)


if __name__ == "__main__":
    main()

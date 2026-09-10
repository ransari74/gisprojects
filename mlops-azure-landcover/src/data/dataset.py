"""torch Dataset + transform builders for EuroSAT, reading the split CSV
produced by download_eurosat.py.
"""
import csv
from pathlib import Path
from typing import Callable, Optional

import yaml
from PIL import Image
from torch.utils.data import Dataset
from torchvision import transforms

CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "data_config.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


class EuroSATSplit(Dataset):
    """Reads rows for a single split ("train"/"val"/"test") from splits.csv."""

    def __init__(self, data_dir: Path, split: str, transform: Optional[Callable] = None):
        self.data_dir = Path(data_dir)
        self.transform = transform
        splits_csv = self.data_dir / "splits.csv"
        if not splits_csv.exists():
            raise FileNotFoundError(
                f"{splits_csv} not found. Run `python -m src.data.download_eurosat "
                f"--data-dir {data_dir}` first."
            )

        self.rows = []
        with open(splits_csv, newline="") as f:
            for row in csv.DictReader(f):
                if row["split"] == split:
                    self.rows.append(row)

        if not self.rows:
            raise ValueError(f"No rows found for split={split!r} in {splits_csv}")

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, idx: int):
        row = self.rows[idx]
        image = Image.open(row["path"]).convert("RGB")
        if self.transform:
            image = self.transform(image)
        return image, int(row["label"])

    @property
    def class_names(self):
        return sorted({r["class_name"] for r in self.rows}, key=lambda c: int(
            next(r["label"] for r in self.rows if r["class_name"] == c)
        ))


def build_transforms(image_size: int, train: bool):
    cfg = load_config()["image"]
    ops = [
        transforms.Resize((image_size, image_size)),
    ]
    if train:
        ops += [
            transforms.RandomHorizontalFlip(),
            transforms.RandomVerticalFlip(),
            transforms.RandomRotation(15),
        ]
    ops += [
        transforms.ToTensor(),
        transforms.Normalize(mean=cfg["normalize_mean"], std=cfg["normalize_std"]),
    ]
    return transforms.Compose(ops)

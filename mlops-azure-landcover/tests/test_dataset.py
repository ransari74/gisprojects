import csv

import pytest
from torchvision import transforms

from src.data.dataset import EuroSATSplit, build_transforms


def _write_fake_splits_csv(tmp_path, image_path):
    splits_csv = tmp_path / "splits.csv"
    with open(splits_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["path", "label", "class_name", "split"])
        writer.writerow([str(image_path), 0, "Forest", "train"])
        writer.writerow([str(image_path), 1, "Highway", "val"])
    return splits_csv


def _make_fake_image(tmp_path):
    from PIL import Image
    image_path = tmp_path / "fake.jpg"
    Image.new("RGB", (64, 64), color=(10, 20, 30)).save(image_path)
    return image_path


def test_missing_splits_csv_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        EuroSATSplit(tmp_path, "train")


def test_split_filters_rows(tmp_path):
    image_path = _make_fake_image(tmp_path)
    _write_fake_splits_csv(tmp_path, image_path)

    train_ds = EuroSATSplit(tmp_path, "train")
    val_ds = EuroSATSplit(tmp_path, "val")

    assert len(train_ds) == 1
    assert len(val_ds) == 1
    assert train_ds[0][1] == 0
    assert val_ds[0][1] == 1


def test_unknown_split_raises(tmp_path):
    image_path = _make_fake_image(tmp_path)
    _write_fake_splits_csv(tmp_path, image_path)

    with pytest.raises(ValueError):
        EuroSATSplit(tmp_path, "test")


def test_build_transforms_train_vs_eval():
    train_tf = build_transforms(image_size=224, train=True)
    eval_tf = build_transforms(image_size=224, train=False)

    assert isinstance(train_tf, transforms.Compose)
    assert isinstance(eval_tf, transforms.Compose)
    assert len(train_tf.transforms) > len(eval_tf.transforms)

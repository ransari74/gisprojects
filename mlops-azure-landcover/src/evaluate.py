"""Evaluate a trained checkpoint on the held-out test split and log a
confusion matrix + classification report to MLflow.
"""
import argparse
from pathlib import Path

import mlflow
import timm
import torch
from sklearn.metrics import classification_report, confusion_matrix
from torch.utils.data import DataLoader

from src.data.dataset import EuroSATSplit, build_transforms


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("./data"))
    parser.add_argument("--arch", default="resnet18")
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--image-size", type=int, default=224)
    parser.add_argument("--batch-size", type=int, default=64)
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    test_ds = EuroSATSplit(args.data_dir, "test", build_transforms(args.image_size, train=False))
    test_loader = DataLoader(test_ds, batch_size=args.batch_size, shuffle=False)

    num_classes = len(set(int(r["label"]) for r in test_ds.rows))
    model = timm.create_model(args.arch, pretrained=False, num_classes=num_classes)
    model.load_state_dict(torch.load(args.checkpoint, map_location=device))
    model.to(device).eval()

    all_preds, all_labels = [], []
    with torch.no_grad():
        for images, labels in test_loader:
            outputs = model(images.to(device))
            all_preds.extend(outputs.argmax(dim=1).cpu().tolist())
            all_labels.extend(labels.tolist())

    report = classification_report(all_labels, all_preds, digits=4)
    cm = confusion_matrix(all_labels, all_preds)
    print(report)
    print("Confusion matrix:\n", cm)

    if not mlflow.get_tracking_uri() or mlflow.get_tracking_uri().startswith("file:"):
        mlflow.set_tracking_uri("file:./mlruns")
    mlflow.set_experiment("eurosat-landcover")
    with mlflow.start_run(run_name=f"evaluate-{args.arch}"):
        mlflow.log_text(report, "test_classification_report.txt")
        mlflow.log_text(str(cm), "test_confusion_matrix.txt")


if __name__ == "__main__":
    main()

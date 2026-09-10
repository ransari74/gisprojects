"""Fine-tune a pretrained backbone (ResNet18, EfficientNet-B0, or ViT-Tiny)
on EuroSAT. Used both for the three architecture-comparison jobs and, with
different --lr/--weight-decay, for the Azure ML sweep job over the winning
architecture.
"""
import argparse
from pathlib import Path

import mlflow
import timm
import torch
import torch.nn as nn
from sklearn.metrics import accuracy_score, f1_score
from torch.utils.data import DataLoader

from src.data.dataset import EuroSATSplit, build_transforms

ARCH_CHOICES = ["resnet18", "efficientnet_b0", "vit_tiny_patch16_224"]


def build_model(arch: str, num_classes: int) -> nn.Module:
    return timm.create_model(arch, pretrained=True, num_classes=num_classes)


def set_backbone_trainable(model: nn.Module, trainable: bool, arch: str) -> None:
    """Freeze everything except the classification head."""
    head_names = {
        "resnet18": "fc",
        "efficientnet_b0": "classifier",
        "vit_tiny_patch16_224": "head",
    }
    head = head_names.get(arch, "")
    for name, param in model.named_parameters():
        if not name.startswith(head):
            param.requires_grad = trainable


def run_epoch(model, loader, criterion, optimizer, device, train: bool):
    model.train() if train else model.eval()
    total_loss, all_preds, all_labels = 0.0, [], []

    with torch.set_grad_enabled(train):
        for images, labels in loader:
            images, labels = images.to(device), labels.to(device)
            outputs = model(images)
            loss = criterion(outputs, labels)

            if train:
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

            total_loss += loss.item() * images.size(0)
            all_preds.extend(outputs.argmax(dim=1).cpu().tolist())
            all_labels.extend(labels.cpu().tolist())

    avg_loss = total_loss / len(loader.dataset)
    acc = accuracy_score(all_labels, all_preds)
    f1 = f1_score(all_labels, all_preds, average="macro")
    return avg_loss, acc, f1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("./data"))
    parser.add_argument("--arch", choices=ARCH_CHOICES, default="resnet18")
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--weight-decay", type=float, default=1e-5)
    parser.add_argument("--freeze-backbone-epochs", type=int, default=1)
    parser.add_argument("--image-size", type=int, default=224)
    parser.add_argument("--output-dir", type=Path, default=Path("./outputs"))
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    if not mlflow.get_tracking_uri() or mlflow.get_tracking_uri().startswith("file:"):
        mlflow.set_tracking_uri("file:./mlruns")
    mlflow.set_experiment("eurosat-landcover")

    train_ds = EuroSATSplit(args.data_dir, "train", build_transforms(args.image_size, train=True))
    val_ds = EuroSATSplit(args.data_dir, "val", build_transforms(args.image_size, train=False))
    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True, num_workers=2)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size, shuffle=False, num_workers=2)

    num_classes = len(set(int(r["label"]) for r in train_ds.rows))
    model = build_model(args.arch, num_classes).to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    best_f1 = -1.0

    with mlflow.start_run(run_name=f"finetune-{args.arch}"):
        mlflow.log_params({
            "model": args.arch,
            "epochs": args.epochs,
            "batch_size": args.batch_size,
            "lr": args.lr,
            "weight_decay": args.weight_decay,
            "freeze_backbone_epochs": args.freeze_backbone_epochs,
            "image_size": args.image_size,
        })

        for epoch in range(args.epochs):
            set_backbone_trainable(model, trainable=epoch >= args.freeze_backbone_epochs, arch=args.arch)

            train_loss, train_acc, train_f1 = run_epoch(model, train_loader, criterion, optimizer, device, train=True)
            val_loss, val_acc, val_f1 = run_epoch(model, val_loader, criterion, optimizer, device, train=False)

            mlflow.log_metrics({
                "train_loss": train_loss, "train_accuracy": train_acc, "train_f1_macro": train_f1,
                "val_loss": val_loss, "val_accuracy": val_acc, "val_f1_macro": val_f1,
            }, step=epoch)
            print(f"[{args.arch}] epoch {epoch+1}/{args.epochs} "
                  f"train_loss={train_loss:.4f} val_acc={val_acc:.4f} val_f1={val_f1:.4f}")

            if val_f1 > best_f1:
                best_f1 = val_f1
                ckpt_path = args.output_dir / f"{args.arch}_best.pt"
                torch.save(model.state_dict(), ckpt_path)

        mlflow.log_metric("best_val_f1_macro", best_f1)
        mlflow.pytorch.log_model(model, artifact_path="model")
        print(f"Best val_f1_macro for {args.arch}: {best_f1:.4f}")


if __name__ == "__main__":
    main()

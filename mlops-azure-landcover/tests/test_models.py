import torch

from src.models.finetune import ARCH_CHOICES, build_model, set_backbone_trainable


def test_build_model_output_shape():
    for arch in ARCH_CHOICES:
        model = build_model(arch, num_classes=10)
        model.eval()
        dummy = torch.randn(2, 3, 224, 224)
        with torch.no_grad():
            out = model(dummy)
        assert out.shape == (2, 10), f"unexpected output shape for {arch}: {out.shape}"


def test_set_backbone_trainable_freezes_non_head_params():
    model = build_model("resnet18", num_classes=10)
    set_backbone_trainable(model, trainable=False, arch="resnet18")

    frozen = [p.requires_grad for name, p in model.named_parameters() if not name.startswith("fc")]
    head = [p.requires_grad for name, p in model.named_parameters() if name.startswith("fc")]

    assert all(not g for g in frozen)
    assert all(head)

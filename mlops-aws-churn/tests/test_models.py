import torch

from src.models.train_nn import ChurnNet


def test_churnnet_output_shape():
    model = ChurnNet(input_dim=20, hidden_dims=[64, 32], dropout=0.2)
    dummy = torch.randn(8, 20)
    out = model(dummy)
    assert out.shape == (8,)


def test_churnnet_handles_single_sample():
    model = ChurnNet(input_dim=20, hidden_dims=[64, 32], dropout=0.2)
    model.eval()
    dummy = torch.randn(1, 20)
    with torch.no_grad():
        out = model(dummy)
    assert out.shape == (1,)

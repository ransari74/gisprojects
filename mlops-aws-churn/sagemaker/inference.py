"""SageMaker inference handler for the churn NN model (used when the
PyTorch NN candidate wins). Implements the four functions the PyTorch
Inference Toolkit looks for: model_fn, input_fn, predict_fn, output_fn.
"""
import json
import os

import torch

from src.models.train_nn import ChurnNet

FEATURE_DIM = None  # set at model_fn time from the saved checkpoint metadata


def model_fn(model_dir):
    checkpoint = torch.load(os.path.join(model_dir, "churn_nn.pt"), map_location="cpu")
    metadata_path = os.path.join(model_dir, "model_metadata.json")
    with open(metadata_path) as f:
        metadata = json.load(f)

    model = ChurnNet(
        input_dim=metadata["input_dim"],
        hidden_dims=metadata["hidden_dims"],
        dropout=metadata["dropout"],
    )
    model.load_state_dict(checkpoint)
    model.eval()
    return model


def input_fn(request_body, content_type="application/json"):
    if content_type != "application/json":
        raise ValueError(f"Unsupported content type: {content_type}")
    payload = json.loads(request_body)
    return torch.tensor(payload["instances"], dtype=torch.float32)


def predict_fn(input_tensor, model):
    with torch.no_grad():
        logits = model(input_tensor)
        return torch.sigmoid(logits)


def output_fn(prediction, accept="application/json"):
    return json.dumps({"churn_probability": prediction.tolist()}), accept

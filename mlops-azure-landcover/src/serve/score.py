"""Azure ML Managed Online Endpoint scoring script.

Must expose init() and run(raw_data) — this is the contract Azure ML's
online deployment runtime expects (see azureml/deployment.yml which points
`code_configuration.scoring_script` at this file).
"""
import base64
import io
import json
import os

import timm
import torch
from PIL import Image
from torchvision import transforms

CLASS_NAMES = [
    "AnnualCrop", "Forest", "HerbaceousVegetation", "Highway", "Industrial",
    "Pasture", "PermanentCrop", "Residential", "River", "SeaLake",
]

model = None
transform = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
])


def init():
    global model
    model_dir = os.getenv("AZUREML_MODEL_DIR", ".")
    checkpoint_path = os.path.join(model_dir, "model", "data", "model.pth")
    model = timm.create_model("resnet18", pretrained=False, num_classes=len(CLASS_NAMES))
    model.load_state_dict(torch.load(checkpoint_path, map_location="cpu"))
    model.eval()


def run(raw_data):
    body = json.loads(raw_data)
    image_bytes = base64.b64decode(body["image_base64"])
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    tensor = transform(image).unsqueeze(0)

    with torch.no_grad():
        logits = model(tensor)
        probs = torch.softmax(logits, dim=1).squeeze(0)
        pred_idx = int(probs.argmax())

    return json.dumps({
        "predicted_class": CLASS_NAMES[pred_idx],
        "confidence": float(probs[pred_idx]),
        "probabilities": {CLASS_NAMES[i]: float(p) for i, p in enumerate(probs)},
    })

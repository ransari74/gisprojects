.PHONY: install lint test data baseline finetune-all

install:
	pip install -r requirements.txt -r requirements-dev.txt

lint:
	ruff check src tests
	black --check src tests

test:
	pytest tests/ -v

data:
	python -m src.data.download_eurosat --data-dir ./data

baseline: data
	python -m src.models.baseline --data-dir ./data

finetune-all: data
	python -m src.models.finetune --data-dir ./data --arch resnet18
	python -m src.models.finetune --data-dir ./data --arch efficientnet_b0
	python -m src.models.finetune --data-dir ./data --arch vit_tiny_patch16_224

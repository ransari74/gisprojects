.PHONY: install lint test data train-all evaluate

install:
	pip install -r requirements.txt -r requirements-dev.txt

lint:
	ruff check src tests sagemaker
	black --check src tests sagemaker

test:
	pytest tests/ -v

data:
	python -m src.data.download_data --output-dir ./data
	python -m src.data.preprocess --input-dir ./data --output-dir ./data/processed

train-all: data
	python -m src.models.baseline --data-dir ./data/processed
	python -m src.models.train_xgboost --data-dir ./data/processed
	python -m src.models.train_lightgbm --data-dir ./data/processed
	python -m src.models.train_nn --data-dir ./data/processed

evaluate:
	python -m src.evaluate --experiments-dir ./experiments

# syntax=docker/dockerfile:1
# The ETL runs as a one-shot job, not a long-lived service.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /work

COPY etl/requirements.txt ./etl/requirements.txt
RUN pip install --no-cache-dir -r etl/requirements.txt

COPY etl ./etl
CMD ["python", "-m", "etl.load", "--generate", "--truncate"]

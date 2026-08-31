#!/usr/bin/env bash
# Build the Lambda container image and push it to your public ECR repo.
#
#   ./scripts/deploy/push-ecr.sh
#
# Builds for arm64 (Lambda Graviton -- cheaper, and matches an Apple Silicon
# build host natively with no QEMU emulation). Requires the AWS CLI
# configured locally (`aws configure`) with ECR push permission.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
require ecr_repo_uri

echo "==> Building $ecr_repo_uri:latest (linux/arm64)..."
docker build --platform linux/arm64 -f "$REPO_ROOT/backend/Dockerfile.lambda" -t "$ecr_repo_uri:latest" "$REPO_ROOT/backend"

echo "==> Logging in to public ECR..."
aws ecr-public get-login-password --region us-east-1 | docker login --username AWS --password-stdin public.ecr.aws

echo "==> Pushing $ecr_repo_uri:latest..."
docker push "$ecr_repo_uri:latest"

echo "==> Pushed. Next: ./scripts/deploy/deploy-lambda.sh"

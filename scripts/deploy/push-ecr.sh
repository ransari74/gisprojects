#!/usr/bin/env bash
# Build the Lambda container image and push it to your private ECR repo.
#
#   ./scripts/deploy/push-ecr.sh
#
# Must be a PRIVATE repo -- Lambda's create-function/update-function-code
# rejects public.ecr.aws images outright ("not valid source image"), it only
# ever pulls from private ECR in the function's own account/region.
#
# Builds for arm64 (Lambda Graviton -- cheaper, and matches an Apple Silicon
# build host natively with no QEMU emulation). Requires the AWS CLI
# configured locally (`aws configure`) with ECR push permission.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
require ecr_repo_uri

echo "==> Building $ecr_repo_uri:latest (linux/arm64)..."
docker build --platform linux/arm64 -f "$REPO_ROOT/backend/Dockerfile.lambda" -t "$ecr_repo_uri:latest" "$REPO_ROOT/backend"

REGISTRY_HOST="${ecr_repo_uri%%/*}"
echo "==> Logging in to $REGISTRY_HOST..."
aws ecr get-login-password --region "$aws_region" | docker login --username AWS --password-stdin "$REGISTRY_HOST"

echo "==> Pushing $ecr_repo_uri:latest..."
docker push "$ecr_repo_uri:latest"

echo "==> Pushed. Next: ./scripts/deploy/deploy-lambda.sh"

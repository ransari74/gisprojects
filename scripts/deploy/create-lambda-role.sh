#!/usr/bin/env bash
# One-time: create a minimal IAM execution role for the Lambda function.
# Safe to re-run -- prints the existing role's ARN instead of failing if it's
# already there.
#
#   ./scripts/deploy/create-lambda-role.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

TRUST_POLICY='{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "lambda.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}'

if aws iam get-role --role-name "$lambda_role_name" >/dev/null 2>&1; then
    echo "==> Role $lambda_role_name already exists."
else
    echo "==> Creating role $lambda_role_name..."
    aws iam create-role \
        --role-name "$lambda_role_name" \
        --assume-role-policy-document "$TRUST_POLICY" >/dev/null

    aws iam attach-role-policy \
        --role-name "$lambda_role_name" \
        --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

    echo "==> Waiting for IAM propagation..."
    sleep 10
fi

ROLE_ARN="$(aws iam get-role --role-name "$lambda_role_name" --query 'Role.Arn' --output text)"
echo "==> Role ARN: $ROLE_ARN"
echo
echo "Add this to your .env if you want to skip this lookup next time:"
echo "  lambda_role_arn='$ROLE_ARN'"

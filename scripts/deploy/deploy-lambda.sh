#!/usr/bin/env bash
# Create (first run) or update (later runs) the Lambda function from whatever
# image is currently at $ecr_repo_uri:latest, set its env vars, and make sure
# it has a public Function URL.
#
#   ./scripts/deploy/push-ecr.sh        # build + push the image first
#   ./scripts/deploy/deploy-lambda.sh   # then this
#
# Re-run after changing cors_origins (or anything else) in your .env, or
# after pushing a new image, to pick up the change.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
require pg_uri
require ecr_repo_uri

# --- role ARN -----------------------------------------------------------
if [ -n "${lambda_role_arn:-}" ]; then
    ROLE_ARN="$lambda_role_arn"
elif aws iam get-role --role-name "$lambda_role_name" >/dev/null 2>&1; then
    ROLE_ARN="$(aws iam get-role --role-name "$lambda_role_name" --query 'Role.Arn' --output text)"
else
    echo "No Lambda execution role found. Run ./scripts/deploy/create-lambda-role.sh first." >&2
    exit 1
fi

# --- secret key: generate once, persist to the env file ------------------
if [ -z "${secret_key:-}" ]; then
    echo "==> No secret_key set -- generating one and saving it to $ENV_FILE"
    secret_key="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
    printf "\nsecret_key='%s'\n" "$secret_key" >> "$ENV_FILE"
fi

IMAGE_URI="$ecr_repo_uri:latest"
ENV_VARS="Variables={DATABASE_URL=$pg_uri,SECRET_KEY=$secret_key,CORS_ORIGINS=$cors_origins,SEED_DEMO_USERS=$seed_demo_users}"

if aws lambda get-function --function-name "$lambda_function_name" --region "$aws_region" >/dev/null 2>&1; then
    echo "==> $lambda_function_name exists -- updating code and config..."
    aws lambda update-function-code \
        --function-name "$lambda_function_name" \
        --image-uri "$IMAGE_URI" \
        --region "$aws_region" >/dev/null
    aws lambda wait function-updated --function-name "$lambda_function_name" --region "$aws_region"

    aws lambda update-function-configuration \
        --function-name "$lambda_function_name" \
        --environment "$ENV_VARS" \
        --region "$aws_region" >/dev/null
    aws lambda wait function-updated --function-name "$lambda_function_name" --region "$aws_region"
else
    echo "==> Creating $lambda_function_name..."
    aws lambda create-function \
        --function-name "$lambda_function_name" \
        --package-type Image \
        --code ImageUri="$IMAGE_URI" \
        --architectures arm64 \
        --role "$ROLE_ARN" \
        --timeout 30 \
        --memory-size 512 \
        --environment "$ENV_VARS" \
        --region "$aws_region" >/dev/null
    aws lambda wait function-active --function-name "$lambda_function_name" --region "$aws_region"
fi

# --- function URL ---------------------------------------------------------
if ! aws lambda get-function-url-config --function-name "$lambda_function_name" --region "$aws_region" >/dev/null 2>&1; then
    echo "==> Creating public Function URL..."
    aws lambda create-function-url-config \
        --function-name "$lambda_function_name" \
        --auth-type NONE \
        --region "$aws_region" >/dev/null
    # A resource-based policy is required separately for auth-type NONE to
    # actually be reachable without an AWS SigV4-signed request.
    aws lambda add-permission \
        --function-name "$lambda_function_name" \
        --statement-id FunctionURLAllowPublicAccess \
        --action lambda:InvokeFunctionUrl \
        --principal '*' \
        --function-url-auth-type NONE \
        --region "$aws_region" >/dev/null 2>&1 || true
fi

FUNCTION_URL="$(aws lambda get-function-url-config --function-name "$lambda_function_name" --region "$aws_region" --query FunctionUrl --output text)"
echo
echo "==> Deployed. Function URL: $FUNCTION_URL"
echo "    Health check: ${FUNCTION_URL}health"

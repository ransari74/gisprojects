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

# Each Lambda execution environment holds its own connection pool -- the
# app's defaults (pool_size=5, max_overflow=10 -- sane for one persistent
# server handling many requests) let a SINGLE instance open up to 15
# connections. Aiven's free tier caps max_connections at 20 total, so two
# concurrent instances at default settings can exhaust it by themselves.
# 1 + 1 per instance, combined with the reserved-concurrency cap below,
# keeps the fleet-wide total safely under the limit.
db_pool_size="${db_pool_size:-1}"
db_max_overflow="${db_max_overflow:-1}"
# Ceiling on simultaneous warm instances -- without this, a burst of tile
# requests (one map view = dozens of concurrent tiles) scales Lambda
# horizontally with no regard for how many DB connections that implies.
lambda_reserved_concurrency="${lambda_reserved_concurrency:-10}"
# This is a public, shared demo -- anonymous visitors get the admin login,
# but can't actually create/delete/reassign real users or roles (see
# app/api/admin.py's _block_if_demo_read_only). Reads (list users/roles/
# audit log) stay live so the RBAC model is still fully explorable.
demo_read_only="${demo_read_only:-true}"

IMAGE_URI="$ecr_repo_uri:latest"
ENV_VARS="Variables={DATABASE_URL=$pg_uri,SECRET_KEY=$secret_key,CORS_ORIGINS=$cors_origins,SEED_DEMO_USERS=$seed_demo_users,DB_POOL_SIZE=$db_pool_size,DB_MAX_OVERFLOW=$db_max_overflow,DEMO_READ_ONLY=$demo_read_only}"

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
    # NONE auth means "no identity check", not "no resource-policy check" --
    # a public Function URL needs BOTH of these statements. Missing either
    # one produces a 403 that looks identical to a misconfigured auth type
    # (found this the hard way: AuthType NONE + only the first statement
    # still 403s). The console adds both automatically when you create a
    # NONE Function URL there; the CLI does not.
    aws lambda add-permission \
        --function-name "$lambda_function_name" \
        --statement-id FunctionURLAllowPublicAccess \
        --action lambda:InvokeFunctionUrl \
        --principal '*' \
        --function-url-auth-type NONE \
        --region "$aws_region" >/dev/null
    aws lambda add-permission \
        --function-name "$lambda_function_name" \
        --statement-id FunctionURLAllowPublicInvoke \
        --action lambda:InvokeFunction \
        --principal '*' \
        --region "$aws_region" >/dev/null
fi

# --- concurrency cap (protects the DB connection limit, not a Lambda quota concern) ---
# Only settable if the account's total concurrency limit leaves room for both
# this reservation AND AWS's own required minimum of 10 unreserved -- a new
# AWS account starts capped at exactly 10 total, which leaves zero room for
# any reservation at all. In that case the account's own ceiling already
# caps concurrent instances at 10, so this is a no-op, not a gap: request an
# AWS service-quota increase for Lambda concurrent executions if you want an
# explicit, lower cap than the account-wide limit.
ACCOUNT_LIMIT="$(aws lambda get-account-settings --region "$aws_region" --query 'AccountLimit.ConcurrentExecutions' --output text)"
if [ "$((ACCOUNT_LIMIT - lambda_reserved_concurrency))" -ge 10 ]; then
    echo "==> Capping reserved concurrency at $lambda_reserved_concurrency (Aiven free tier: 20 max_connections total)..."
    aws lambda put-function-concurrency \
        --function-name "$lambda_function_name" \
        --reserved-concurrent-executions "$lambda_reserved_concurrency" \
        --region "$aws_region" >/dev/null
else
    echo "==> Skipping reserved-concurrency cap: account limit is $ACCOUNT_LIMIT, which doesn't leave AWS's required 10 unreserved after a $lambda_reserved_concurrency reservation."
    echo "    The account's own $ACCOUNT_LIMIT-execution ceiling already caps concurrency for now."
fi

FUNCTION_URL="$(aws lambda get-function-url-config --function-name "$lambda_function_name" --region "$aws_region" --query FunctionUrl --output text)"
echo
echo "==> Deployed. Function URL: $FUNCTION_URL"
echo "    Health check: ${FUNCTION_URL}health"

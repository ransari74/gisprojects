#!/usr/bin/env bash
# Shared setup for the deploy/*.sh scripts: locates the repo root, loads
# secrets from an .env file kept OUTSIDE the repo (one directory above it,
# e.g. /Users/you/freelance/.env for a checkout at /Users/you/freelance/gisprojects),
# so nothing here ever risks a `git add .` picking up real credentials.
#
# Override the location with ENV_FILE=/path/to/file before calling a script
# if yours lives somewhere else.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/../.env}"

if [ ! -f "$ENV_FILE" ]; then
    echo "No env file at $ENV_FILE -- create it (see scripts/deploy/env.example) or set ENV_FILE=..." >&2
    exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

require() {
    local name="$1"
    if [ -z "${!name:-}" ]; then
        echo "Missing '$name' in $ENV_FILE -- see scripts/deploy/env.example" >&2
        exit 1
    fi
}

# If aws_profile is set, every aws CLI call in these scripts uses it instead
# of silently falling back to `default` -- important on a machine that
# already has other AWS profiles configured (work/client accounts) so this
# personal-account deploy can never accidentally land in the wrong one.
if [ -n "${aws_profile:-}" ]; then
    export AWS_PROFILE="$aws_profile"
fi

# Defaults for anything optional -- required vars are checked by each script
# via require(), since not every script needs every variable.
aws_region="${aws_region:-us-east-1}"
lambda_function_name="${lambda_function_name:-gis-portfolio-api}"
lambda_role_name="${lambda_role_name:-gis-portfolio-api-lambda-role}"
seed_demo_users="${seed_demo_users:-true}"
cors_origins="${cors_origins:-http://localhost:5173}"

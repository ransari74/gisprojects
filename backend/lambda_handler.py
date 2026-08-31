"""AWS Lambda entrypoint -- wraps the same FastAPI app the Docker/uvicorn
deployments serve, via a Lambda Function URL (no API Gateway).

Not used by docker-compose or any other deployment target; this file only
matters inside the Lambda container image (see Dockerfile.lambda).
"""

from mangum import Mangum

from app.main import app

# lifespan="auto" runs the app's startup/shutdown (schema check, demo user
# seed) once per cold start, same as it runs once per uvicorn process
# elsewhere -- Lambda reuses a warm container across invocations, so this
# isn't paying that cost on every request.
handler = Mangum(app, lifespan="auto")

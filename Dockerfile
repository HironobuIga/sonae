# Sonae — Amazon Bedrock AgentCore Runtime container
# AgentCore invokes the HTTP contract served by BedrockAgentCoreApp on :8080.
FROM public.ecr.aws/docker/library/python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY deploy/agentcore/entrypoint.py deploy/agentcore/entrypoint.py
COPY scenarios/ scenarios/
COPY examples/ examples/

# Containers are recycled, so durable household state is required here: the
# runtime refuses to start unless SONAE_S3_BUCKET names a bucket YOUR account
# owns (pass it at deploy time — no account-specific default is baked in).
# Set SONAE_REQUIRE_S3=0 for a throwaway run with ephemeral, in-container state.
ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    SONAE_DATA_DIR=/tmp/sonae-data \
    SONAE_REQUIRE_S3=1

EXPOSE 8080
CMD ["python", "deploy/agentcore/entrypoint.py"]

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

ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    SONAE_DATA_DIR=/tmp/sonae-data

EXPOSE 8080
CMD ["python", "deploy/agentcore/entrypoint.py"]

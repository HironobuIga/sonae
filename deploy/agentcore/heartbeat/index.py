"""Sonae ambient heartbeat: invoke the AgentCore runtime's watch_cycle."""
import json
import os

import boto3

RUNTIME_ARN = os.environ["RUNTIME_ARN"]
HOUSEHOLD = os.environ.get("HOUSEHOLD", "aoki")


def handler(event, context):
    client = boto3.client("bedrock-agentcore")
    resp = client.invoke_agent_runtime(
        agentRuntimeArn=RUNTIME_ARN,
        runtimeSessionId=f"sonae-ambient-watch-{HOUSEHOLD}-000000000000000",
        payload=json.dumps({"action": "watch_cycle", "household": HOUSEHOLD}).encode(),
        contentType="application/json",
        accept="application/json",
    )
    body = resp["response"].read().decode()[:800]
    print("watch_cycle:", body)
    return {"ok": True, "body": body}

# Deploying Sonae on Amazon Bedrock AgentCore

Sonae's cloud shape: **AgentCore Runtime** hosts the agent team; **EventBridge Scheduler** provides the
heartbeat that makes the Sentinel ambient; household state persists outside the container.

```
EventBridge Scheduler ──(every 5 min: {"action":"watch_cycle",...})──▶ AgentCore Runtime
                                                                        └─ Sonae agents (Strands)
Web dashboard / CLI ──(onboard / replay / status)──────────────────────▲
Model calls ──▶ Amazon Bedrock (Claude)      State ──▶ S3-backed store / AgentCore Memory
```

## Prerequisites

- AWS account with Bedrock model access (Claude Sonnet) in your region
- `uv sync` done locally, plus: `uv pip install bedrock-agentcore bedrock-agentcore-starter-toolkit`
- Docker (the starter toolkit builds the container image)

## Steps

```bash
cd <repo root>

# 1. Configure the runtime from the entrypoint (creates .agentcore.yaml + Dockerfile)
agentcore configure --entrypoint deploy/agentcore/entrypoint.py --name sonae

# 2. Launch to your account (builds, pushes to ECR, creates the AgentCore Runtime)
agentcore launch

# 3. Smoke-test: onboard the demo family in the cloud
agentcore invoke '{"action":"onboard","profile":'"$(cat examples/aoki_family.json)"',"approve":true}'

# 4. One live watch cycle against real JMA feeds
agentcore invoke '{"action":"watch_cycle","household":"aoki"}'
```

## Making the watch ambient

Create a schedule that invokes the runtime every 5 minutes (agent runtime ARN from `agentcore status`):

```bash
aws scheduler create-schedule \
  --name sonae-watch-aoki \
  --schedule-expression "rate(5 minutes)" \
  --flexible-time-window Mode=OFF \
  --target '{
    "Arn": "arn:aws:scheduler:::aws-sdk:bedrockagentcore:invokeAgentRuntime",
    "RoleArn": "<scheduler-role-arn>",
    "Input": "{\"agentRuntimeArn\": \"<agent-runtime-arn>\", \"payload\": \"{\\\"action\\\": \\\"watch_cycle\\\", \\\"household\\\": \\\"aoki\\\"}\"}"
  }'
```

During calm weather each cycle is a cheap no-op (feed fetch, no new signals, no model tokens beyond
the Sentinel skip-path); during an event it runs the full verified pipeline.

## State

The demo store is filesystem JSON (`SONAE_STORE_DIR`). For multi-tenant cloud use, mount durable
storage or use the AgentCore Memory adapter so each household's plan, watch state, and flight
recorder survive container recycling. Notifications dispatch through the channel layer — swap the
inbox channel for LINE/SES/SNS in `sonae/channels/`.

## Observability

Strands emits OpenTelemetry traces natively; AgentCore Observability picks them up without code
changes. Each household's flight-recorder journal complements the traces with a family-readable
audit trail.

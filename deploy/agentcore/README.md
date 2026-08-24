# Deploying Sonae on Amazon Bedrock AgentCore

Sonae's cloud shape: **AgentCore Runtime** hosts the agent team; **EventBridge Scheduler** provides the
heartbeat that makes the Sentinel ambient; household state persists outside the container.

```
EventBridge Scheduler ──(every 5 min: {"action":"watch_cycle",...})──▶ AgentCore Runtime
                                                                        └─ Sonae agents (Strands)
Web dashboard / CLI ──(onboard / replay / status)──────────────────────▲
Model calls ──▶ Amazon Bedrock (Claude)      State ──▶ AgentCore Memory / mounted store
```

These steps are the ones we actually ran for this submission (AgentCore CLI ≥ 0.27, CDK-based).

## Prerequisites

- AWS account with Bedrock model access (Claude Sonnet 4.6) in your region
- Docker, Node.js, and the AgentCore CLI: `npm install -g @aws/agentcore`
- A `requirements.txt` at the repo root (regenerate with
  `uv export --no-dev --format requirements-txt --no-hashes > requirements.txt`,
  then append `bedrock-agentcore`); the repo's `Dockerfile` builds the runtime container

## Steps

```bash
# 1. Create the CDK-managed AgentCore project (already committed under deploy/sonae)
cd deploy && agentcore create --no-agent --project-name sonae && cd sonae

# 2. Register the Sonae repo as a bring-your-own Container agent
agentcore add agent --name sonae --type byo --build Container --language Python \
  --framework Strands --model-provider Bedrock \
  --code-location /path/to/agent-for-human-hackson-2026 \
  --entrypoint deploy/agentcore/entrypoint.py --protocol HTTP

# 3. Deploy (CDK bootstrap on first run, container build & push, runtime creation)
agentcore deploy --yes

# 4. Runtime ARN + status
agentcore status --json
```

## Invoking

The runtime speaks raw JSON payloads (the same shape EventBridge sends). The `agentcore invoke`
convenience command wraps its argument as `{"prompt": ...}`, so for Sonae's action payloads call the
runtime API directly:

```bash
ARN="arn:aws:bedrock-agentcore:us-west-2:<account>:runtime/sonae_sonae-XXXX"

aws bedrock-agentcore invoke-agent-runtime --agent-runtime-arn "$ARN" \
  --payload "$(echo -n '{"action":"status","household":"aoki"}' | base64)" \
  --content-type application/json --accept application/json out.json && cat out.json

# Onboard the demo family in the cloud (runs the full verification graph; allow ~10 min)
python -c 'import json,base64;print(base64.b64encode(json.dumps({"action":"onboard","profile":json.load(open("examples/aoki_family.json")),"approve":True}).encode()).decode())' > payload.b64
aws bedrock-agentcore invoke-agent-runtime --agent-runtime-arn "$ARN" \
  --payload file://payload.b64 --cli-read-timeout 900 \
  --content-type application/json --accept application/json out.json && cat out.json

# One live watch cycle against real JMA feeds
aws bedrock-agentcore invoke-agent-runtime --agent-runtime-arn "$ARN" \
  --payload "$(echo -n '{"action":"watch_cycle","household":"aoki"}' | base64)" \
  --content-type application/json --accept application/json out.json && cat out.json
```

## Verified cloud run (2026-08-23)

Actual responses from our deployed runtime (`sonae_sonae-OBwRHO2xdW`, us-west-2):

```jsonc
// onboard (full self-correcting graph ran in the cloud, ~9 min;
// note the revision loop converging: planner↔verifier twice)
{"household": "aoki", "hazards_at_risk": ["flood", "earthquake"], "steps": 5,
 "verified": true,
 "agent_path": ["cartographer", "planner", "verifier", "planner", "verifier", "planner", "verifier"]}

// watch_cycle, same session — live JMA feed, calm day: the zero-token ambient path
{"processed_events": 0, "dispatched": 0, "note": "no new events"}

// status, same session — state persisted across invocations
{"activated_level": 0, "plan_approved": true, "last_checked": "2026-08-23T09:46:26Z"}
```

## Making the watch ambient

> Current state in our account: fully built and verified end-to-end (schedule → Lambda → runtime →
> JMA → S3), then **paused** (`--state DISABLED`) to keep the sandbox quiet between demos.
> Re-enable for a live demonstration with:
> `aws scheduler update-schedule --name sonae-watch-aoki ... --state ENABLED`

A small Lambda invokes the runtime's `watch_cycle`, and EventBridge Scheduler fires it every five
minutes. (A Lambda hop is used because `InvokeAgentRuntime` is a streaming API, which EventBridge
universal targets don't drive directly.)

```bash
# Lambda (see heartbeat/index.py in this directory): boto3 bedrock-agentcore
# InvokeAgentRuntime with a fixed runtimeSessionId and {"action":"watch_cycle",...}
aws lambda create-function --function-name sonae-heartbeat \
  --runtime python3.12 --handler index.handler --zip-file fileb://heartbeat.zip \
  --role <lambda-role-with-InvokeAgentRuntime> --timeout 600 \
  --environment 'Variables={RUNTIME_ARN=<agent-runtime-arn>,HOUSEHOLD=aoki}'

aws scheduler create-schedule --name sonae-watch-aoki \
  --schedule-expression "rate(5 minutes)" --flexible-time-window Mode=OFF \
  --target '{"Arn":"<lambda-arn>","RoleArn":"<scheduler-role>","Input":"{}"}'
```

During calm weather each cycle is a cheap no-op (feed fetch, dedup, **zero model tokens**); when a
new official signal appears it runs the verified pipeline. Verified output of one live cycle:

```json
{"processed_events": 0, "dispatched": 0, "note": "no new events"}
```

## State (durable via S3)

`SONAE_S3_BUCKET` is **passed at deploy time** — no bucket is baked into the image, so nothing can
silently target an account you don't own. With it set, every invocation pulls the household's store
from `s3://<bucket>/store/<household>/` and pushes it back afterwards — plans, watch state, and the
flight recorder survive container recycling, so the scheduled watch is genuinely stateful. The
runtime's execution role needs Get/Put/List on that bucket. The image sets `SONAE_REQUIRE_S3=1`, so
a container started without a bucket fails loudly instead of quietly losing state on recycle; set
`SONAE_REQUIRE_S3=0` for a throwaway run with ephemeral in-container state. Local runs stay purely
file-based.

```bash
# our verified deployment (bucket created in the same account as the runtime)
aws s3 mb s3://sonae-store-$(aws sts get-caller-identity --query Account --output text)
agentcore deploy --env SONAE_S3_BUCKET=sonae-store-<account-id>
```

Notifications dispatch through the channel layer — swap the inbox channel for LINE/SES/SNS in
`sonae/channels/`.

## Observability

Strands emits OpenTelemetry traces natively; AgentCore Observability picks them up without code
changes (`agentcore obs`, or CloudWatch: `/aws/bedrock-agentcore/runtimes/<runtime-id>`). Each
household's flight-recorder journal complements the traces with a family-readable audit trail.

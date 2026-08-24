# An agent whose job is to do nothing (almost always): ambient watch loops on Bedrock AgentCore

*Draft for builder.aws — article 3 of 3 for the Agents for Humans Hackathon (Sonae project).
Commands below are the ones we ran for our deployed runtime (AgentCore CLI, `npm i -g @aws/agentcore`).*

Most agent demos are conversations: a human asks, an agent answers. Sonae's most important agent
never gets asked anything. The Sentinel watches Japan Meteorological Agency feeds for one family's
exact warning area, around the clock, and its correct output on almost every invocation is:
*nothing happens*. On a five-minute heartbeat that is 288 invocations a day, essentially all of
which end in "stand by." The shape only pays off the night a typhoon comes and the same loop says
"Level 4 — complete the evacuation now," and a 78-year-old leaves her house while it's still light.

This article covers the architecture of that ambient shape on Amazon Bedrock AgentCore: how to
host a Strands agent team that mostly sleeps, what the heartbeat looks like, and the cost and
safety properties that fall out.

## The shape: heartbeat → runtime → verified pipeline

AgentCore Runtime hosts our container and exposes the invocation contract; the ambient behavior
comes from an EventBridge Scheduler rule invoking one action every five minutes:

```json
{"action": "watch_cycle", "household": "aoki"}
```

One deployment serves every operation as a payload-selected action — onboarding, replay, status,
and the watch cycle — so the whole team ships as a single artifact:

```python
app = BedrockAgentCoreApp()

@app.entrypoint
def invoke(payload: dict) -> dict:
    action = payload.get("action", "status")
    if action == "watch_cycle":
        events = jma.fetch_active_warnings(household.jma_office_code, household.jma_class20_code)
        return process_events(store, events, channel)   # Sentinel → Messenger → Verifier → dispatch
    ...
```

The watch cycle is cheap by design, in three tiers:

1. **Zero-token tier.** Fetch the feed, dedup against the watch state. No new signals → no model
   call at all. This is the outcome of almost every cycle, and it costs feed-fetch pennies.
2. **One-decision tier.** New signals → one Sentinel invocation with structured output. Its prompt
   enforces geographic discipline (another basin's alert is not our signal) and monotonic
   activation (never re-announce a level already active). Most storm days are a handful of these.
3. **Full-pipeline tier.** A signal that activates a plan step runs Messenger + Verifier and
   dispatches per-member notifications. In our replay of Typhoon Hagibis this fired **four times
   across thirteen official events** — and the storm day itself, from the first Chikuma flood
   advisory at 13:40 to the mayor's Level 5 broadcast at 02:12, is twelve and a half hours. Downstream
   at Tategahana the Chikuma crested at 12.46 m, the highest since observations began in 1949
   ([Nikkei](https://vdata.nikkei.com/newsgraphics/destruction-map-chikumagawa/)). Four dispatches.
   Everything else was "stand by."

## Why a runtime, not a Lambda cron

You could run tier 1 in a Lambda. The reasons the runtime shape wins for agent teams:

- **One artifact, many behaviors.** Onboarding runs a self-correcting Strands Graph for several
  minutes — outside comfortable Lambda interaction patterns, trivial for AgentCore's long-running
  invocations. The heartbeat and the heavyweight planning share one container, one set of
  dependencies, one deployment.
- **Session/state separation.** Household state (the approved plan, watch level, flight-recorder
  journal) lives outside the container; the runtime stays stateless and recyclable.
- **Observability for free.** Strands emits OpenTelemetry natively; AgentCore Observability picks
  up the traces without code changes. For a safety-critical agent, "what did it read and when"
  is not a nice-to-have.

## Deploying

The current AgentCore CLI drives everything through CDK. With a Dockerfile at the repo root:

```bash
npm install -g @aws/agentcore
agentcore create --no-agent --project-name sonae
cd sonae
agentcore add agent --name sonae --type byo --build Container --language Python \
  --framework Strands --model-provider Bedrock \
  --code-location /path/to/sonae --entrypoint deploy/agentcore/entrypoint.py
agentcore deploy --yes
agentcore invoke '{"action": "watch_cycle", "household": "aoki"}'
```

Then the heartbeat (EventBridge Scheduler → InvokeAgentRuntime) makes it ambient. Full templates
live in our repo's `deploy/` directory.

## The safety properties of boring

Two properties of this shape matter more than any prompt:

- **The quiet path is the tested path.** Because "stand by" is the overwhelmingly common outcome,
  a real storm exercises the same dedup, state, and decision code that the heartbeat has already run
  288 times a day, every day, on nothing at all. There is no cold "emergency mode" that first runs
  the night it matters.
- **Silence is observable.** Every cycle journals what it fetched and decided, even when the
  decision is nothing. A watchdog that might be dead and a watchdog that verifiably chose to stay
  quiet look identical from the outside — unless you log the choice. We log the choice.

*Sonae is open source (MIT): Strands Agents SDK on Amazon Bedrock AgentCore, fed entirely by
Japan's government open data.*

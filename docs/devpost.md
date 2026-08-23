# Devpost submission — Sonae (draft)

**Track:** Good Neighbor Agents
**Elevator:** The agent team that stands watch over your family — it builds your household's
evacuation plan from Japan's official hazard data, monitors government feeds around the clock, and
when the water rises, runs the plan person-by-person, in each person's language.

---

## Inspiration

On the night of October 12, 2019, Typhoon Hagibis pushed the Chikuma River over its levee at
Hoyasu, Nagano. The city's evacuation order came at 23:40 — in darkness and driving rain. But the
river had been on flood-warning footing since 17:30, in daylight. The information that could have
bought families six hours was public the entire time; what they lacked was someone on watch who
knew what it meant *for their house, their mother, their street*.

Japan's Cabinet Office asks every household to prepare a "My-Timeline" — a personal evacuation
plan bound to official alert levels. It's the right idea, and almost nobody does it, because it
means hours of hazard-map reading and shelter research. Homework assigned to 125 million people.
About 80% of Japan's flood fatalities are people aged 65+ — and the hardest case is the one
millions live with: an aging parent alone in the family home, hours away.

## What it does

**Prepare (5 minutes).** Give Sonae an address and your family's reality — "mother, 78, bad knees,
no car." A Cartographer agent reads the statutory hazard maps at that exact coordinate (this demo
home: 10–20 m expected flood depth), finds designated evacuation sites *per hazard* (the nearest
site to our demo home is earthquake-designated but NOT flood-designated — most families never
learn this), and a Planner turns it into a family timeline keyed to the official 5-level alert
framework. An adversarial Verifier re-derives every claim from the same government data before the
family ever sees it. The family approves the plan once, calmly — that approval is the
authorization boundary.

**Watch (always).** A Sentinel monitors JMA warning feeds for that household's exact warning area.
Boring is the normal case; that's the job.

**Act (the bad night).** When official signals cross the plan's triggers, Sonae activates the
right step — elderly members start moving at Level 3, which is literally what Level 3 exists
for — and messages each family member *their* tasks in *their* language: big simple Japanese steps
for grandmother, situational English for her son abroad, every claim cited to its official source,
every message gated by the Verifier. If verification can't converge during a Level 3+ event, Sonae
relays the official text verbatim instead of staying silent: AI prose fails closed, the signal
fails open.

**Remember.** Everything agents read, decide, and send is journaled per household — a flight
recorder, the same audit discipline Japan's post-event verification reports apply to municipal
decisions.

## How we built it

- **Strands Agents SDK** — the planning pipeline is a Strands `Graph` with a conditional revision
  edge: Cartographer → Planner → Verifier, where a rejection routes back to the Planner with a
  mechanical fix instruction (`reset_on_revisit`, bounded executions). The watch pipeline chains
  Sentinel → Messenger → Verifier with Pydantic-validated JSON as the inter-agent protocol and a
  `BeforeToolCall`/`AfterToolCall` hook journaling every tool call.
- **Japan government open data as tools** — JMA warning/forecast feeds; GSI geocoders; the
  national designated-evacuation-site registry (per-hazard suitability flags under the Disaster
  Countermeasures Basic Act); and the statutory hazard-map raster tiles, which we sample at the
  home's coordinates and decode against the official depth legend.
- **Amazon Bedrock** (Claude Sonnet 4.5) for all agents; **Amazon Bedrock AgentCore Runtime** for
  cloud deployment with an EventBridge Scheduler heartbeat making the Sentinel ambient.
- **The replay engine** — our demo replays Typhoon Hagibis minute-by-minute from the official
  chronology in Nagano City's disaster-response verification report (15 river flood-forecast
  bulletins and every municipal evacuation order, pp. 24–28), driving the identical pipeline that
  live JMA feeds drive.

## Challenges

- **An agent must not hallucinate in this domain.** Our first live run proved the point: the
  Planner invented a plausible city phone number, and the Verifier caught it before it shipped.
  We kept that behavior and hardened the loop: the verifier accepts the official alert-level
  equivalence table as ground truth, rejects only contradictions or unsupported safety-critical
  specifics, and must phrase rejections as mechanical edits.
- **Point-querying hazard maps.** There is no API for "flood depth at this coordinate" — we
  sample the national hazard-tile rasters and decode the official legend colors, validated
  against the 2020 Kuma River flood zone.
- **Honesty in the demo.** We refused to stage a fictional disaster. Reconstructing the real
  official timeline made the demo stronger: our counterfactual — evacuation starting at 17:30
  instead of 23:40 — is grounded in the public record.

## Accomplishments

- The full loop works on real data end-to-end: real hazard depths, real shelters, real feeds.
- The verification gate caught a real hallucination on its first live run.
- The dashboard renders the actual GSI hazard map with the home, the inundation zone, and the
  evacuation route — no mockups anywhere in the video.

## What's next

- LINE Messaging integration (how Japanese families actually talk) and safety check-in fan-out
  for neighborhood associations (自主防災会) — the paper name-list problem.
- More feeds: earthquake early warning, river gauге telemetry, L-Alert.
- Country adapters: the architecture is data-driven — NOAA/NWS + FEMA shelters would port it.

## Built with

`strands-agents` · Amazon Bedrock (Claude Sonnet 4.5) · Amazon Bedrock AgentCore · Python ·
FastAPI · Leaflet · JMA open feeds · GSI hazard tiles & evacuation-site registry

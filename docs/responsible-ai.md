# Responsible AI design — Sonae

Sonae operates in a safety-critical domain: what a family does during a flood. This document states
exactly what the system is allowed to do, how it can fail, and what stands between a language model
and a 78-year-old's phone.

## Scope: organize and relay, never predict or overrule

Sonae's agents are permitted to:

1. **Read** official government data (hazard maps, shelter registries, JMA feeds).
2. **Organize** it into a family plan whose *triggers are official signals* (the Cabinet Office
   5-level alert framework), approved by the family in advance.
3. **Relay** official signals mapped to that plan, with citations.

Sonae's agents are prohibited, by prompt and by pipeline structure, from:

- predicting river behavior, rainfall, or timing beyond what officials state;
- issuing an evacuation judgment that has no official signal behind it;
- softening, delaying, or overriding any official instruction;
- sending any factual claim that failed verification.

The system prompt of every agent encodes these rules, but prompts are not the enforcement
mechanism — the pipeline is: the Sentinel only sees official events; the Messenger only sees the
Sentinel's decision, the approved plan, and the events; the Verifier gates dispatch.

## The authorization boundary: family approval

The moment of human judgment is moved from the worst possible time (2 a.m., rising water) to the best
(a calm afternoon). The family reviews the generated plan — evacuate at Level 3 because of Yoshiko's
knees, the primary site, the backup — and approves it. The stored `family_approved` flag is the
Sentinel's authorization to act without further confirmation. No approved plan, no notifications: the
watch pipeline refuses to dispatch.

## Failure-mode analysis

| Failure | Consequence | Mitigation |
|---|---|---|
| Model hallucinates a fact (depth, shelter, level semantics) | Family acts on wrong information | Verifier audits every claim against official data / verbatim events; unverified prose is never sent |
| Verification cannot converge during a Level 3+ event | Family gets nothing — the worst outcome | **Fail-open for the signal**: raw official text is relayed verbatim with citations (no AI prose) |
| Feed outage / endpoint change | Missed signals | Multi-endpoint data layer with caching; watch loop logs every poll; roadmap: redundant feeds (L-Alert) |
| Stale shelter data (provider-documented lag) | Wrong destination | Provider caveat carried into every recommendation; plan lists a backup site |
| Over-alerting ("crying wolf") | Family learns to ignore Sonae | Sentinel activates only *beyond* the current level, only for the household's own area; de-escalation is reserved to humans |
| Agent crash mid-pipeline | Silent failure | Errors are journaled to the flight recorder and surfaced in the UI; watch state is persistent and resumable |

## Auditability

Every tool call, decision, and dispatched notification is journaled per household (the flight
recorder), with timestamps and inputs/outputs. After an event — real or replayed — the family can see
exactly which official bulletin triggered which message. Japan audits its municipal disaster
responses in public verification reports; software that participates in those nights should meet the
same standard.

## Data protection

Household profiles (addresses, family details, health notes) stay in the household's own store —
local files in the demo, per-tenant AgentCore Memory in cloud deployment. The only data sent to
external services are coordinates and area codes sent to government endpoints, and prompts sent to
the configured model provider. No third-party analytics, no data resale, MIT-licensed code.

## Honest demo policy

The demo replays Typhoon Hagibis (2019) using the official post-event chronology, clearly labeled as
a reconstruction, with sources cited in the scenario file itself. We do not stage fictional disasters
as if they were live, and the live-watch mode shown runs against today's real JMA feeds.

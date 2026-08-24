# Sonae (そなえ) — the agent team that stands watch over your family

> Japan tells every family to prepare a personal evacuation timeline. Doing it properly takes hours
> of hazard-map reading, shelter research, and family coordination — so it stays on the to-do list.
> **Sonae is a team of Strands agents that does that work in minutes, then stays on watch over
> official government feeds, and — when the water rises — runs your family's plan, person by person,
> in each person's language.**

Built for the **AWS Agents for Humans Hackathon** (Good Neighbor track) with the
[Strands Agents SDK](https://strandsagents.com/) and Japan's government open data.

**Demo video:** _(link)_ · **Live demo:** _(link)_

![Sonae dashboard during the Typhoon Hagibis replay](docs/screenshots/dashboard-replay.png)
*Mid-replay, all content agent-generated: the home (amber) sits in the Chikuma River's 10–20 m
statutory inundation zone; the plan's steps light up as official signals fire; each family member's
phone receives their instructions, verified before dispatch — Japanese for grandmother, English for
the son and daughter who live far away — with safety check-in buttons, and the neighborhood
association board on the right.*

---

## The problem

- Japan's Cabinet Office urges every household to prepare a **My-Timeline (マイ・タイムライン)** — a
  pre-agreed plan of who does what at each official alert level. Making one means reading your
  municipality's statutory hazard-map booklets — a separate map per hazard — then cross-checking the
  designated-shelter list to find which site is designated for *which* hazard, then negotiating with
  your family. It is homework assigned to a country of over 120 million people, and the work itself
  is the barrier.
- **In Japan's recent flood disasters, 65–80% of those who died were aged 65 or over** — about 65% in
  the 2019 East Japan Typhoon, about 79% in the July 2020 heavy rain
  ([Cabinet Office / MHLW material](https://www.mhlw.go.jp/content/12300000/001075647.pdf);
  [Cabinet Office White Paper on Disaster Management FY2021](https://www.bousai.go.jp/kaigirep/hakusho/r03/honbun/0b_1s_02_01.html)).
  The hardest case is the one millions of adult children live with: an aging parent alone in the
  family home, hours away.
- The night of Typhoon Hagibis (October 12, 2019), Nagano City issued its evacuation order
  (避難指示・緊急) for the Chikuma riverside at **23:40 — in darkness and driving rain**. The signals had
  been arriving since the afternoon: a Chikuma flood advisory at **13:40**, then at **15:30** the first
  **大雨特別警報** ever issued for Nagano Prefecture — nearly two hours before sunset (17:16 JST) — and a
  river flood *warning* bulletin at **17:30**. People with time to leave didn't know their window was
  closing. The river began overtopping the levee at Hoyasu at **01:08**, and the city announced the
  breach — about 70 m wide — at **06:00**; the Naganuma district flooded to roof height. Flooding in
  Nagano City covered 1,541 ha and damaged more than 4,000 buildings.
  (Chronology: [Nagano City post-event verification report](https://www.city.nagano.nagano.jp/documents/1803/346440.pdf), pp. 24–28.)

Alert apps broadcast the same warning to everyone. **What families lack is not information — it's
execution:** a plan made calmly in advance, personalized to grandma's knees, and someone who never
sleeps binding tonight's official signals to that plan.

## What Sonae does

| Phase | What happens | Agents |
|---|---|---|
| **Prepare** (5 min) | Give it an address and your family's reality ("mother, 78, bad knees, no car"). It reads the statutory hazard maps at that exact point, picks designated evacuation sites *per hazard*, and drafts the family My-Timeline — then an adversarial verifier re-derives every claim from official data before you see it. | Cartographer → Planner → Verifier |
| **Watch** (always) | It monitors JMA warning feeds for that household's exact warning area. Nothing happening is the normal, boring case — that's the job. | Sentinel |
| **Act** (the bad night) | When official signals cross the plan's triggers, it activates the right step — not the whole plan — and messages each family member *their* tasks, in *their* language. Every message is verified against the official events before dispatch, and the family-facing copies carry the source link. Elderly-first at Level 3, exactly what Level 3 exists for. | Sentinel → Messenger → Verifier |
| **Recover** | Safety check-ins fan out across the household and the neighborhood circle, and a Coordinator consolidates them into a report. *(Roadmap: post-disaster paperwork guidance — 罹災証明書, support programs — is not implemented.)* | Coordinator |

## Why this is an agent, not an app

Yahoo! Bosai and NERV broadcast alerts — one message, everyone, no memory. Sonae:

- **holds state**: your family, your plan, what level is already activated, what was already sent;
- **makes scoped decisions**: "does *this* bulletin, for *this* river, activate *this* step?" — and stands by
  through dozens of irrelevant signals without crying wolf;
- **acts**: composes and dispatches per-person instructions, in Japanese for grandma, English for the adult children who live far away;
- **audits itself**: every claim is checked against official sources before it ships, and every tool call is
  journaled to a per-household flight recorder — the same discipline Japan's post-event verification
  reports apply to municipal decisions, applied to the agents.

## Architecture

![Sonae architecture](docs/architecture.png)

**AWS deployment view** ([editable draw.io source](docs/architecture-aws.drawio)):

![Sonae on AWS](docs/architecture-aws.png)

<details>
<summary>Same architecture as mermaid (text)</summary>

```mermaid
flowchart TB
  subgraph prepare["PREPARE — Strands Graph (self-correcting)"]
    C[Cartographer<br/>hazard analyst] --> P[Planner<br/>My-Timeline designer]
    P --> V[Verifier<br/>adversarial fact-checker]
    V -- "rejected + revision request" --> P
  end

  subgraph data["Japan gov open data (tools)"]
    G1[GSI geocoder]
    G2[Hazard-map tiles<br/>flood / surge / tsunami / landslide]
    G3[Designated evacuation sites<br/>nationwide, per-hazard flags]
    G4[JMA warning & forecast feeds]
  end

  subgraph watch["WATCH & ACT — verified pipeline"]
    F[Feed events<br/>live JMA / scenario replay] --> S[Sentinel<br/>watch officer]
    S -- "activate step N" --> M[Messenger<br/>per-member, per-language]
    M --> V2[Verifier<br/>evidence = the events themselves]
    V2 -- approved --> D[Dispatch<br/>console / web inbox / both<br/>LINE: roadmap]
    V2 -- "unverifiable at L3+" --> R[Raw official-text relay<br/>fail-open for the signal,<br/>fail-closed for AI prose]
  end

  C & V -.-> data
  S -.-> ST[(Household store<br/>plan · watch state · flight recorder)]
  M -.-> ST
  prepare --> ST
  ST --> S
```

</details>

**Strands features used:** multi-agent `Graph` with a conditional revision edge (the verification loop),
tool use over government open data, hook providers (`BeforeToolCall`/`AfterToolCall` flight recorder),
Pydantic-validated JSON inter-agent protocol, model-agnostic providers (Bedrock default, Anthropic API
fallback).

**Cloud (built and verified in our account):** the team runs on **Amazon Bedrock AgentCore Runtime**
(BYO container via the AgentCore CLI/CDK); household state is durable in S3 across container
recycling; an EventBridge Scheduler → Lambda heartbeat drives `watch_cycle` every 5 minutes
(currently paused between demos). The full chain — schedule → runtime → live JMA feeds → S3 state —
is verified end-to-end, including a complete onboarding graph run inside the cloud runtime whose
`agent_path` shows the verification loop converging. See [`deploy/agentcore/`](deploy/agentcore/).

## The trust layer

An agent that tells your mother when to leave her home must not hallucinate. Sonae's answer is layered:

1. **No originated judgments.** Sonae maps official signals onto the family's approved plan; it never
   originates an evacuation judgment of its own. The approval (human-in-the-loop) happens calmly, in
   advance, not at 2 a.m. **One deviation is encoded as an explicit, reviewable rule rather than
   improvised:** a 大雨特別警報 is Level-5-equivalent for rainfall, but Sonae pushes the plan's Level 4
   *"complete the evacuation"* step, because national guidance is to finish horizontal evacuation
   while routes are still usable; Level 5 ("protect yourself where you are") is reserved for signals
   that inundation is actually occurring. This is the one place Sonae's mapping departs from a literal
   reading of the plan's trigger text, and it is a written policy, not a runtime improvisation: it
   lives in the Sentinel's and Verifier's prompts ([`src/sonae/agents/prompts.py`](src/sonae/agents/prompts.py)),
   and every time it fires the household journal records which level was activated and on which event.
2. **Independent re-verification.** The onboarding Verifier holds the same government-data tools and
   re-derives depths, distances, and shelter designations itself before approving the plan. In the watch
   pipeline, drafts are audited against the verbatim official events.
3. **Verified before dispatch, cited where a citation helps.** Every dispatched message is verified
   against the official source before it is sent, and the messages to the remote family members carry
   that source as a link. The message to the elderly recipient at home is deliberately kept short and
   actionable — big plain steps, no citation footer. That is a legibility choice about who has to act
   on it, not a gap in verification: the same Verifier gated it.
4. **Asymmetric failure.** AI prose fails **closed** (unverified text is never sent). The signal fails
   **open**: if composition can't be verified during a Level 3+ event, Sonae relays the official text
   verbatim rather than staying silent.
5. **Flight recorder.** Every tool call and decision is journaled per household and replayable.

## Government open data used

| Source | What Sonae reads | Access |
|---|---|---|
| [JMA warning/forecast feeds](https://www.jma.go.jp/bosai/) | Live warnings & advisories per municipal warning area | public JSON |
| [GSI hazard-map portal](https://disaportal.gsi.go.jp/) | Statutory flood / storm-surge / tsunami depths, landslide zones at the home's coordinates | open raster tiles (legend-decoded) |
| [GSI evacuation-site data](https://hinanmap.gsi.go.jp/) | All designated emergency evacuation sites nationwide with per-hazard suitability (Disaster Countermeasures Basic Act art. 49-4) | open CSV |
| [GSI geocoders](https://msearch.gsi.go.jp/) | Address → coordinates → municipality | public API |
| [Nagano City verification report](https://www.city.nagano.nagano.jp/documents/1803/346440.pdf) et al. | Minute-accurate official chronology for the Typhoon Hagibis replay | public PDF |

Data caveats required by the providers (e.g. "shelter data may lag municipal updates") are carried
through the pipeline and shown to users — relaying caveats is part of relaying data.

## Quickstart

```bash
git clone https://github.com/HironobuIga/sonae.git && cd sonae
uv sync

# Model provider (pick one)
export AWS_PROFILE=your-profile AWS_REGION=us-west-2   # Amazon Bedrock (default)
# or: export SONAE_MODEL_PROVIDER=anthropic ANTHROPIC_API_KEY=sk-ant-...

# 1. Onboard the demo family (grandmother by the Chikuma River, son and daughter far away)
uv run sonae onboard examples/aoki_family.json --approve

# 2. Replay the night of Typhoon Hagibis against the plan (official chronology)
uv run sonae replay aoki scenarios/hagibis_2019_nagano.json --pause

# 3. Or watch live JMA feeds for the household's real warning area
uv run sonae watch aoki --interval 300

# Web dashboard (what the demo video shows)
uv run uvicorn sonae.web.app:app --port 8000   # → http://localhost:8000
```

Tests run fully offline against bundled data extracts: `uv run pytest`.

## Not just one town

Sonae's inputs are one address and a family description; everything else comes from nationwide
standardized open data, so it generalizes to any Japanese municipality. We onboarded a second
household through the web form — a single-story home in Hitoyoshi, Kumamoto (Kuma River basin,
devastated in July 2020) with an 82-year-old who uses a cane and is hard of hearing. The agents
produced a completely different plan: primary evacuation site 80 m away, "call Shigeru — speak
loudly and slowly", car keys ready by Level 2 because he needs extra time. Same architecture, no
city-specific code.

![Hitoyoshi household](docs/screenshots/dashboard-hitoyoshi.png)

## The 2019 counterfactual

This is a counterfactual reconstructed from the replay, not an observed outcome for a real household.
Run the replay and watch the timestamps. Nagano City's evacuation order for the riverside districts
came at **23:40**, in darkness. In the replay, the 大雨特別警報 lands at **15:30** and Sonae's verified
push goes out at **15:31** — **8 hours 9 minutes of warning lead** before the official order, and the
last clearly-daylight window of the day (sunset was 17:16 JST). The approved plan allows Yoshiko
**90–120 minutes** to walk the 2.63 km to her flood-designated shelter, so on that timeline she is inside
it around **17:31** — roughly a **6-hour safety margin** ahead of the order that the real residents of
Hoyasu received. Every timestamp comes from the official record; the plan came from the same hazard
maps anyone could have read. That margin is the product.

## Responsible AI

See [docs/responsible-ai.md](docs/responsible-ai.md): scope limits (organize & relay official
information, never predict or advise beyond it), the verification gate, failure-mode analysis, and why
family approval is the authorization boundary. Sonae is a preparedness aid, not a replacement for
official warnings — municipal instructions always take precedence.

## License

[MIT](LICENSE). Built with respect for the people of the Chikuma River valley, and for every family
whose group chat lights up when the rain starts.

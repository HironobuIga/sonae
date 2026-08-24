# Devpost submission — Sonae (draft)

**Track:** Good Neighbor Agents
**Elevator:** The agent team that stands watch over your family — it builds your household's
evacuation plan from Japan's official hazard data, monitors government feeds around the clock, and
when the water rises, runs the plan person-by-person, in each person's language.

---

## Inspiration

On the night of October 12, 2019, Typhoon Hagibis pushed the Chikuma River over its levee at
Hoyasu, Nagano. The city's evacuation order for the riverside districts came at 23:40 — in darkness
and driving rain. But the signals had been arriving since the afternoon: a Chikuma flood advisory at
13:40, the first 大雨特別警報 ever issued for Nagano Prefecture at 15:30 — nearly two hours before
sunset — and a river flood-warning bulletin at 17:30. The information that could have bought
families the better part of ten hours was public the entire time; what they lacked was someone on watch who knew
what it meant *for their house, their mother, their street*.

Japan's Cabinet Office asks every household to prepare a "My-Timeline" — a personal evacuation
plan bound to official alert levels. It's the right idea, and the work is the barrier: hours of
hazard-map reading (a separate statutory map per hazard) and shelter research (which designated
site covers *which* hazard). Homework assigned to a country of over 120 million people. In Japan's
recent flood disasters, 65–80% of those who died were aged 65 or over — about 65% in the 2019 East
Japan Typhoon, about 79% in the July 2020 heavy rain
([Cabinet Office / MHLW](https://www.mhlw.go.jp/content/12300000/001075647.pdf);
[Cabinet Office White Paper on Disaster Management FY2021](https://www.bousai.go.jp/kaigirep/hakusho/r03/honbun/0b_1s_02_01.html))
— and the hardest case is the one millions live with: an aging parent alone in the family home,
hours away.

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
for grandmother, situational English for the son and daughter who live far away. Every message is
verified against the official events before dispatch, and the copies to the remote family members
carry the source link; grandmother's is deliberately kept short and actionable, with no citation
footer, because she is the one who has to walk. One system-side rule is written down
rather than improvised: a 大雨特別警報 is formally Level-5-equivalent for rainfall, but Sonae pushes
the plan's Level 4 *"complete the evacuation"* step, because national guidance is to finish
horizontal evacuation while routes are still usable — Level 5 is reserved for signals that
inundation is actually occurring. If verification can't converge during a Level 3+ event, Sonae
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
- **Amazon Bedrock** (Claude Sonnet 4.6) for all agents; **Amazon Bedrock AgentCore Runtime** hosts
  the team in production — deployed with the AgentCore CLI (CDK) as a bring-your-own container, with
  an EventBridge Scheduler heartbeat making the Sentinel ambient. The same payload-selected
  entrypoint serves onboarding, watch cycles, and replay.
- **The replay engine** — our demo replays Typhoon Hagibis minute-by-minute from the official
  chronology in Nagano City's disaster-response verification report (pp. 24–28), the MLIT Hokuriku
  damage report, and the JMA Nagano weather report. The scenario file encodes 13 events: 6 of the
  report's 15 designated-river flood-forecast bulletins (the ones that move the household's
  situation — the rest are referenced inside the event bodies), the municipal evacuation notices for
  the riverside districts, and the JMA emergency warning. It drives the identical pipeline that live
  JMA feeds drive.

## Challenges

- **An agent must not hallucinate in this domain.** Our live runs proved the point, and the journal
  in `data/store/aoki/watch.json` records each catch. A draft told a family member to look up "the
  Nagano City disaster hotline" — a contact detail with no source anywhere in the evidence bundle;
  the Verifier flagged it `unsupported` and demanded the sentence be deleted. At the replay's pivotal
  moment (the 15:30 emergency warning), the Messenger's draft subject line for grandmother read
  避難指示 — an "evacuation order" no municipality had issued yet — and the Verifier rejected it with a
  mechanical fix (change the subject to 大雨特別警報); the corrected message went out verified, minutes
  later, still hours ahead of the real order. Other catches in the same journal: a shelter address
  that differed from the approved plan by one character, and the household's exact address appearing
  in a message with no source behind it. We hardened the loop from these: the verifier accepts the
  official alert-level equivalence table as ground truth, rejects only contradictions or unsupported
  safety-critical specifics, and must phrase rejections as mechanical edits.
- **Point-querying hazard maps.** There is no API for "flood depth at this coordinate" — we
  sample the national hazard-tile rasters and decode the official legend colors against the
  statutory MLIT legend, and every result ships with the portal and legend spec as its source.
- **Honesty in the demo.** We refused to stage a fictional disaster. Reconstructing the real
  official timeline made the demo stronger — and it is labelled for what it is: a counterfactual
  from the replay, not something that happened to anyone. In it, the verified push goes out at
  **15:31**, 8 hours 9 minutes of warning lead ahead of the 23:40 order; with the plan's 90–120 minute
  walking allowance, grandmother is inside the shelter around 17:31, roughly a 6-hour safety margin.

## Accomplishments

- The full loop works on real data end-to-end: real hazard depths, real shelters, real feeds.
- The verification gate caught real unsupported claims on live runs — an unsourced disaster-hotline
  instruction, an over-claimed 避難指示 subject line, a mismatched shelter address, the household's
  exact address — all stopped before dispatch, all in the journal.
- The complete ambient chain is built and verified in AWS: EventBridge Scheduler → Lambda →
  AgentCore Runtime → live JMA feeds → durable S3 household state — including a full onboarding
  graph run *inside* the cloud runtime whose agent path shows the self-correction loop converging.
- Generality proven with a second city: a Hitoyoshi (Kuma River) household onboarded through the
  web form got a completely different, equally personalized plan — shelter 80 m away, phone calls
  "loud and slow" for a hard-of-hearing 82-year-old.
- The dashboard renders the actual GSI hazard map with the home, the inundation zone, the
  evacuation route, and the historical levee-breach point — no mockups anywhere in the video.

## What's next

- LINE Messaging integration (how Japanese families actually talk) and safety check-in fan-out
  for neighborhood associations (自主防災会) — the paper name-list problem.
- More feeds: earthquake early warning, river gauge telemetry, L-Alert.
- Country adapters: the architecture is data-driven — NOAA/NWS + FEMA shelters would port it.

## Built with

`strands-agents` · Amazon Bedrock (Claude Sonnet 4.6) · Amazon Bedrock AgentCore · Python ·
FastAPI · Leaflet · JMA open feeds · GSI hazard tiles & evacuation-site registry

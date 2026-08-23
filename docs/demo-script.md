# Demo video script — Sonae (5:00 max)

Recording setup: browser at 1600×1000 on `http://localhost:8000/?household=aoki`, dark room OBS or
QuickTime screen recording, narration in English (calm, measured — this is a serious subject; let the
timestamps do the emotional work). Reset state before recording:

```bash
rm -rf data/store/aoki && uv run uvicorn sonae.web.app:app --port 8000
```

Optional insurance: run the flow once beforehand so every tile/font is cached; keep the completed
store from a rehearsal in `data/store-backup/` to cut to if a live step misbehaves.

---

## 0:00–0:35 — The problem (slides / stock B-roll, 3 cards)

> Japan tells every family to prepare a personal evacuation timeline — who does what, at which
> official alert level. It means reading two-hundred-page hazard maps, checking which shelter covers
> which disaster, and negotiating with your family. Homework for 125 million people. Almost no one
> has done it.
>
> And the people with the least time to do it are the ones we worry about most: aging parents, alone
> in the family home. About eighty percent of Japan's flood deaths are people over 65.

Card 1: 政府広報のマイ・タイムライン推奨ページ + a 200-page hazard-map PDF scrolling.
Card 2: "~80% of flood fatalities: age 65+" (cite Cabinet Office).
Card 3: photo-style card: son in Tokyo, mother in Nagano. "This is the Aoki family. It's October 11, 2019."

## 0:35–1:20 — Prepare: the agent team builds the plan (live UI)

Action: click **1 · Protect this home**. While the graph runs, the Agent Activity feed streams tool
calls live. Narrate over it:

> Sonae is a team of Strands agents. Give it one address and three sentences about your family.
> The Cartographer reads the statutory hazard maps at that exact point — this home sits in a 10-to-20
> meter inundation zone of the Chikuma River. It finds the designated evacuation sites — and notices
> what most families never learn: the closest site, 600 meters away, is designated for earthquakes,
> not floods. The Planner turns this into a family timeline, tuned to a 78-year-old's knees.
> And before anything reaches the family, an adversarial Verifier re-derives every claim from the
> same official data. In our first test run it caught the Planner inventing a phone number.
> That's why it exists.

Cut (speed up waiting with a timelapse crossfade). When the plan renders, hover the timeline:

> Level 3 is the heart of it: Yoshiko starts evacuating when the river reaches flood-warning
> footing — hours before a general evacuation order. That is literally what Level 3 exists for.
> The family reviews this once, calmly, and approves it. From here, Sonae is authorized to act.

## 1:20–3:20 — The night of Typhoon Hagibis (replay, the core)

Action: click **2 · Load Hagibis replay** — the amber ribbon appears. Then click **3 · Advance**
through the moments. Pace: linger where it matters.

> What you'll see now is a replay of October 12th, 2019 — every timestamp exactly as officially
> recorded in Nagano City's post-event verification report.

- **10/11 08:46 + 14:00** (advance twice, quick): "The day before: typhoon warnings. Sonae runs
  step one — charge the phone, pack the medication, while the sky is clear."
- **10/12 13:40, 14:55** (quick): "Saturday afternoon: the river reaches advisory levels. Level 2.
  Valuables go upstairs."
- **10/12 15:30** — 大雨特別警報 (pause): "3:30 PM: an emergency heavy-rain warning — the first in
  Nagano's history. Watch the Sentinel: it doesn't panic, it maps the signal to the family's plan."
- **10/12 17:30** — 氾濫警戒情報 (THE moment — slow down): "5:30 PM. The Chikuma River is forecast
  to hit danger level by 7 PM. Level 3 equivalent. **This is the moment.**" — show the phones:
  Yoshiko's message in Japanese, big simple steps; Kenji's in English: *call your mother now, stay
  on the line.* Point at the citation footer. "Every sentence carries its official source, and a
  Verifier signed off before it was sent. **It is still daylight.**"
- **10/12 18:00–18:40** (advance): "By the time the city's blanket advisory arrives, Yoshiko is
  already at the evacuation site — the one designated for floods, outside the inundation zone."
- **10/12 23:40** (pause, let it land): "23:40. The official evacuation order. Darkness, driving
  rain. This is when the real residents of Hoyasu were told to leave. Sonae's family had a
  six-hour head start — from the same public information."
- **10/13 01:15 → 02:12** (advance, quiet): "At 1:08 the river came over the levee at Hoyasu. By
  dawn the neighborhood was under water to the rooftops. The plan's last step isn't evacuation —
  it's making sure no one goes back in."

## 3:20–3:50 — Always on watch (live mode + memory)

Action: terminal split — `uv run sonae watch aoki --once` against today's real JMA feed; then show
the flight-recorder journal.

> This isn't a replay toy. The same pipeline watches the real JMA feeds for this exact warning
> area, around the clock, on Amazon Bedrock AgentCore. Quiet days cost almost nothing. And
> everything the agents read, decide, and send is journaled per household — the same audit
> discipline Japan applies to its municipal disaster response, applied to the AI.

## 3:50–4:25 — Architecture (one diagram slide)

> Built on the Strands Agents SDK: a self-correcting Graph for planning — Cartographer, Planner,
> and a Verifier that rejects until every claim is grounded — and a Sentinel-to-Messenger pipeline
> with one hard rule: AI prose fails closed, but the official signal fails open. If verification
> can't converge during an emergency, Sonae relays the official text verbatim rather than stay
> silent. All data is Japanese government open data: JMA feeds, GSI hazard tiles, the national
> evacuation-site registry.

## 4:25–5:00 — Close

> The information that could have saved hours that night was public the whole time. What families
> lacked was an agent on watch — one that knows your mother's knees, your river, your shelter, and
> exactly which official signal means *go*.
>
> Sonae. そなえ. Built for Japan — and for any country that publishes its hazard data.
> Because the next Hagibis is already forming.

Final card: **Sonae — the agent team that stands watch over your family.** Repo URL + "Built with
Strands Agents SDK on Amazon Bedrock AgentCore".

---

## Shot checklist

- [ ] UI at Level 0 (calm) → onboarding stream → plan render
- [ ] Phones close-up at 17:30 moment (both languages visible)
- [ ] 23:40 pause with plate pulsing L4
- [ ] Map close-up: home in the pink zone, dashed route out of it
- [ ] `sonae watch --once` live terminal
- [ ] Architecture diagram (docs/architecture)
- [ ] Timestamp overlay in corner during replay ("official record: 長野市検証報告書 p.24–28")

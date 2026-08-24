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
> official alert level. It means reading a separate statutory hazard map for floods, for landslides,
> for storm surge, then cross-checking which designated shelter covers which disaster, then
> negotiating with your family. Homework for a country of over a hundred and twenty million people.
> The work is the reason it doesn't get done.
>
> And the people with the least time to do it are the ones we worry about most: aging parents, alone
> in the family home. In Japan's recent flood disasters, sixty-five to eighty percent of the people
> who died were sixty-five or older.

Card 1: 政府広報のマイ・タイムライン推奨ページ + scroll the actual 長野市洪水ハザードマップ PDF and the
separate 指定緊急避難場所 list side by side (the point is *two documents that must be cross-read*, not a
page count).
Card 2: "Recent flood disasters: 65–80% of fatalities were age 65+ — 2019 East Japan Typhoon ≈65%,
July 2020 heavy rain ≈79%." Source line on the card:
`厚生労働省/内閣府 資料 mhlw.go.jp/content/12300000/001075647.pdf · 令和3年版防災白書`
Card 3: photo-style card: son and daughter far away, mother in Nagano. "This is the Aoki family. It's
October 11, 2019."

## 0:35–1:20 — Prepare: the agent team builds the plan (live UI)

Action: click **1 · Protect this home**. While the graph runs, the Agent Activity feed streams tool
calls live. Narrate over it:

> Sonae is a team of Strands agents. Give it one address and three sentences about your family.
> The Cartographer reads the statutory hazard maps at that exact point — this home sits in a 10-to-20
> meter inundation zone of the Chikuma River. It finds the designated evacuation sites — and notices
> what most families never learn: the closest site, 600 meters away, is designated for earthquakes,
> not floods. The Planner turns this into a family timeline, tuned to a 78-year-old's knees.
> And before anything reaches the family, an adversarial Verifier re-derives every claim from the
> same official data. In our runs it caught a draft telling the family to call a city disaster
> hotline that appears in none of the evidence. That's why it exists.

Cut (speed up waiting with a timelapse crossfade). When the plan renders, hover the timeline:

> Level 3 is the heart of it: Yoshiko starts moving when the river reaches flood-warning footing —
> or sooner, if an emergency warning lands first — hours before a general evacuation order. That is
> literally what Level 3 exists for. The family reviews this once, calmly, and approves it. From
> here, Sonae is authorized to act.

## 1:20–3:20 — The night of Typhoon Hagibis (replay, the core)

Action: click **2 · Load Hagibis replay** — the amber ribbon appears. Then click **3 · Advance**
through the moments. Pace: linger where it matters.

> What you'll see now is a replay of October 12th, 2019 — every timestamp exactly as officially
> recorded in Nagano City's post-event verification report.

- **10/11 08:46 + 14:00** (advance twice, quick): "The day before: typhoon warnings. Sonae runs
  step one — charge the phone, pack the medication, while the sky is clear."
- **10/12 13:40, 14:55** (quick): "Saturday afternoon: the river reaches advisory levels. Level 2.
  Valuables go upstairs."
- **10/12 15:30** — 大雨特別警報 (THE moment — slow down): "3:30 PM: an emergency heavy-rain
  warning — the first ever issued for Nagano Prefecture. Formally that's 'Level 5 equivalent.' But
  Level 5 means *protect yourself where you are*, and national guidance is to finish a horizontal
  evacuation while you still can. So Sonae applies a rule it has written down in advance: it
  activates the plan's Level 4 step — *complete the evacuation now.*" — show the phones: Yoshiko's
  message in Japanese, big simple steps — すぐ避難; Kenji's in English: *call your mother now, stay on
  the line.* Point at the citation footer on Kenji's message — and note that his message says out
  loud why Level 4 and not Level 5. "The Verifier signed off on both before they were sent. Kenji's
  carries the source link; grandmother's is deliberately short — four plain paragraphs, no footer,
  because she is the one who has to walk. **Sunset that day was 17:16. This is the last
  clearly-daylight window she gets.**"
- **10/12 16:00 → 18:40** (advance briskly): "Then watch the discipline: landslide advisories for
  other districts, river bulletins the plan already covers — the Sentinel stands by through all of
  them. No spam. A family that trusts its agent is a family that acts when it speaks."
- **10/12 20:50** — 氾濫発生情報 upstream (pause): "8:50 PM: the river starts coming over its
  banks upstream. Level 5 — final confirmation that everyone is out, and no one goes back."
- **10/12 23:40** (pause, let it land): "23:40. The official evacuation order. Darkness, driving
  rain. This is when the real residents of Hoyasu were told to leave. Sonae's push went out at
  **15:31** — **eight hours and nine minutes** of warning lead, from the same public information.
  The plan gives Yoshiko two hours to walk it, so on this timeline she is inside the shelter around
  half past five: about **six hours of safety margin**. To be clear about what you're watching —
  this is a counterfactual from the replay, not something that happened to anyone that night."
- **10/13 01:15 → 02:12** (advance, quiet): "At 1:08 the river began overtopping the levee at
  Hoyasu itself. The city announced the breach — about seventy meters wide — at six in the morning,
  by which time the neighborhood was under water to the rooftops. The journal's last entries read:
  *stand by — nothing left for Sonae to do.*"

## 3:20–3:50 — The neighborhood, and always on watch

Action: scroll to the NEIGHBORHOOD card. Click a check-in button on Yoshiko's phone ("無事です"),
watch the circle counts update; click "Compose coordinator report".

> After the water, Japanese neighborhoods confirm safety with paper name lists carried door to
> door. Sonae's circle mode replaces the paper, not the neighbors: live check-ins across member
> households, and a Coordinator agent that tells the chairman exactly which door to knock on
> first.

Then: terminal split — `uv run sonae watch aoki --once` against today's real JMA feed, and the same
pipeline running in the cloud:

```bash
aws bedrock-agentcore invoke-agent-runtime --agent-runtime-arn $SONAE_ARN \
  --payload "$(echo -n '{"action":"watch_cycle","household":"aoki"}' | base64)" \
  --content-type application/json --accept application/json out.json && cat out.json
```

> Deployed on Amazon Bedrock AgentCore, an EventBridge heartbeat runs this cycle every five
> minutes. On a calm day like today it costs nothing — zero model tokens. Boring is the job.

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
- [ ] Phones close-up at the 15:30 大雨特別警報 moment (both languages visible)
- [ ] 23:40 pause with plate pulsing L4
- [ ] Map close-up: home in the pink zone, dashed route out of it
- [ ] `sonae watch --once` live terminal
- [ ] Architecture diagram (docs/architecture)
- [ ] Timestamp overlay in corner during replay ("official record: 長野市検証報告書 p.24–28")

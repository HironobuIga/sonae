# Demo households — the evidence behind the claims

These files are committed on purpose. Every number in the README, the slides, and
the demo video is quoted from something in this directory, so a reviewer can open
the artifact rather than take our word for it.

The people are invented. `aoki` is the demo family (Yoshiko 78, and her adult
children Kenji and Mika, who live away from home); the neighbouring households in
the `naganuma` circle are fixtures with the same shape. Addresses are
district-level (長野県長野市穂保) or household labels — no real person's home.
`hitoyoshi` is a second city, used to show the pipeline is not tuned to Nagano.

| file | what it is |
|---|---|
| `<household>/household.json` | the intake: who lives there, ages, needs, languages |
| `<household>/hazard_profile.json` | the Cartographer's reading of the statutory hazard maps at that address, with its sources |
| `<household>/plan.json` | the family My-Timeline, and whether the family approved it |
| `<household>/watch.json` | **the flight recorder** — every tool call, Sentinel decision, verification attempt, level clamp, and dispatch, in order |
| `<household>/inbox.json` | the notifications actually delivered, with their citations |
| `<household>/checkins.json` | safety check-ins |
| `_circles/naganuma.json` | the neighbourhood association and its member households |
| `_circles/naganuma.report.json` | the Coordinator's report to the 会長 |

`watch.json` is the one to read first. Search it for `"kind": "verification"` to
see the Verifier rejecting drafts and demanding mechanical fixes, and for
`"kind": "level_clamped"` to see a deterministic guard overruling the Sentinel's
own alert level.

Regenerate everything from live agents and live government data:

```bash
AWS_PROFILE=... scripts/regen_demo.sh
```

That resets this directory, re-runs onboarding, replays Typhoon Hagibis from
`scenarios/hagibis_2019_nagano.json`, and prints the verifier catches from the
run. The exact wording changes between runs — the model is not deterministic —
so re-verify any number quoted in the docs after regenerating.

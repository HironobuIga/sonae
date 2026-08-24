#!/usr/bin/env bash
# Regenerate the committed demo artifacts from a live agent run.
#
#   AWS_PROFILE=... scripts/regen_demo.sh
#
# Rebuilds data/store/aoki from scratch: onboarding graph -> family approval ->
# the full Hagibis replay -> a check-in and a fresh neighborhood report. Every
# artifact the README, the slides, and the video quote comes from this run, so
# rerun it whenever a prompt changes and re-verify the quoted numbers after.
set -euo pipefail
cd "$(dirname "$0")/.."

STORE=data/store/aoki
BACKUP="/tmp/sonae-store-backup-$$"

echo "== backing up current store to $BACKUP =="
mkdir -p "$BACKUP"
cp -R data/store/aoki "$BACKUP/" 2>/dev/null || true
cp -R data/store/_circles "$BACKUP/" 2>/dev/null || true

# Start clean: a leftover watch state would dedup every replay event as already
# seen, and the replay would silently do nothing.
rm -rf "$STORE"

echo "== 1/5 onboarding (cartographer -> planner -> verifier) =="
python3 -m sonae.cli onboard examples/aoki_family.json

echo "== 2/5 family approval =="
python3 -m sonae.cli approve aoki

echo "== plan level triggers after this run =="
python3 - <<'PY'
import json
p = json.load(open("data/store/aoki/plan.json"))
for s in p["steps"]:
    print(f"  L{s['alert_level']}: {s['trigger']}")
print("  family_approved:", p["family_approved"])
print("  primary shelter:", p["primary_shelter"]["name"], p["primary_shelter"]["distance_km"], "km")
PY

echo "== 3/5 replay: Typhoon Hagibis 2019, Chikuma River =="
python3 -m sonae.cli replay aoki scenarios/hagibis_2019_nagano.json

echo "== 4/5 check-ins and neighborhood report =="
python3 -m sonae.cli checkin aoki Yoshiko safe --note "避難所に到着しました"
python3 -m sonae.cli circle-report naganuma

echo "== 5/5 verifier catches recorded in this run =="
python3 - <<'PY'
import json
w = json.load(open("data/store/aoki/watch.json"))
for h in w["history"]:
    if h.get("kind") == "verification":
        state = "APPROVED" if h["approved"] else "REJECTED"
        print(f"  attempt {h['attempt']}: {state} ({h['checks']} checks)")
        for u in h.get("unsupported", []):
            print(f"      unsupported: {u}")
        if h.get("revision_request"):
            print(f"      revision: {h['revision_request'][:160]}")
PY

echo
echo "done. previous store kept at $BACKUP"

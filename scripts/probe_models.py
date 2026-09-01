"""Probe which Bedrock Claude models this account can actually invoke.

    AWS_PROFILE=... python3 scripts/probe_models.py [--region us-west-2]

Listing a model does not mean you can call it — access is gated per account, and
the failure only shows up on invoke. This sends a one-token request to each
candidate and reports OK / the error code, so the project can pick the strongest
model it is actually allowed to use.
"""

from __future__ import annotations

import json
import sys

import boto3
from botocore.exceptions import ClientError

# Strongest first. Ids differ in shape between generations — the 4.6 Opus id ends
# `-v1`, the 4.5 ones carry a date — so each is spelled out rather than generated.
CANDIDATES = [
    "global.anthropic.claude-opus-5",
    "us.anthropic.claude-opus-5",
    "anthropic.claude-opus-5",
    "global.anthropic.claude-fable-5",
    "global.anthropic.claude-sonnet-5",
    "us.anthropic.claude-sonnet-5",
    "global.anthropic.claude-opus-4-8",
    "global.anthropic.claude-opus-4-7",
    "global.anthropic.claude-opus-4-6-v1",
    "us.anthropic.claude-opus-4-6-v1",
    "global.anthropic.claude-opus-4-5-20251101-v1:0",
    "global.anthropic.claude-sonnet-4-6",
    "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "global.anthropic.claude-haiku-4-5-20251001-v1:0",
]

PROBE = {
    "anthropic_version": "bedrock-2023-05-31",
    "max_tokens": 4,
    "messages": [{"role": "user", "content": "hi"}],
}


def main() -> int:
    region = "us-west-2"
    if "--region" in sys.argv:
        region = sys.argv[sys.argv.index("--region") + 1]

    listed: set[str] = set()
    try:
        bedrock = boto3.client("bedrock", region_name=region)
        for m in bedrock.list_foundation_models()["modelSummaries"]:
            listed.add(m["modelId"])
        token = None
        while True:
            kwargs = {"maxResults": 100}
            if token:
                kwargs["nextToken"] = token
            resp = bedrock.list_inference_profiles(**kwargs)
            for p in resp["inferenceProfileSummaries"]:
                listed.add(p["inferenceProfileId"])
            token = resp.get("nextToken")
            if not token:
                break
    except ClientError as exc:
        print(f"(could not list models: {exc.response['Error']['Code']})")

    print(f"region {region}\n")
    runtime = boto3.client("bedrock-runtime", region_name=region)
    working: list[str] = []
    for model_id in CANDIDATES:
        mark = " " if model_id in listed or not listed else "?"
        try:
            runtime.invoke_model(modelId=model_id, body=json.dumps(PROBE))
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            print(f"  {mark} {model_id:<52} {code}")
            continue
        except Exception as exc:  # noqa: BLE001 - report anything else verbatim
            print(f"  {mark} {model_id:<52} {type(exc).__name__}")
            continue
        print(f"  {mark} {model_id:<52} OK")
        working.append(model_id)

    print()
    if working:
        print("invocable:")
        for model_id in working:
            print(f"  {model_id}")
        print(f"\nto use the strongest one:\n  SONAE_BEDROCK_MODEL_ID={working[0]}")
    else:
        print("no candidate model was invocable in this region")

    # Anything Claude-shaped we did not think to try.
    extra = sorted(m for m in listed if "claude" in m.lower() and m not in CANDIDATES)
    if extra:
        print("\nother Claude ids visible to this account (not probed):")
        for model_id in extra:
            print(f"  {model_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

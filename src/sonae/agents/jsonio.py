"""Strict-but-forgiving JSON I/O between agents.

Agents are instructed to emit bare JSON as their final message. Models
occasionally wrap output in fences or prose; we extract the first balanced
JSON object and validate it with the target Pydantic model so downstream
code only ever sees typed, schema-checked data.
"""

from __future__ import annotations

import json
from typing import TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class AgentOutputError(RuntimeError):
    def __init__(self, message: str, raw: str):
        super().__init__(message)
        self.raw = raw


def extract_json(text: str) -> str:
    """Return the first balanced top-level JSON object in `text`."""
    start = text.find("{")
    if start == -1:
        raise AgentOutputError("no JSON object found in agent output", text)
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
        elif ch == '"':
            in_string = not in_string
        elif not in_string:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
    raise AgentOutputError("unbalanced JSON object in agent output", text)


def parse_as(model: type[T], text: str) -> T:
    """Extract and validate agent output as `model`."""
    raw = extract_json(text)
    try:
        return model.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise AgentOutputError(f"agent output failed {model.__name__} validation: {exc}", text) from exc


def schema_block(model: type[BaseModel], exclude: set[str] | None = None) -> str:
    """Render a model's JSON schema for inclusion in an agent prompt.

    `exclude` drops top-level fields the agent must not author (e.g. a human
    sign-off flag): the model is never shown the field, so it cannot set it.
    """
    schema = model.model_json_schema()
    for field in exclude or ():
        schema.get("properties", {}).pop(field, None)
        if field in schema.get("required", []):
            schema["required"].remove(field)
    return json.dumps(schema, ensure_ascii=False, indent=1)

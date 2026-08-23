import pytest
from pydantic import BaseModel

from sonae.agents.jsonio import AgentOutputError, extract_json, parse_as


class Point(BaseModel):
    x: int
    y: int


def test_extract_bare_json():
    assert extract_json('{"x": 1, "y": 2}') == '{"x": 1, "y": 2}'


def test_extract_from_fenced_prose():
    text = 'Here is the result:\n```json\n{"x": 1, "y": {"a": "}"}}\n```\ndone'
    assert extract_json(text) == '{"x": 1, "y": {"a": "}"}}'


def test_extract_handles_braces_in_strings():
    text = 'prefix {"x": "a { b } c", "y": 2} suffix'
    assert extract_json(text) == '{"x": "a { b } c", "y": 2}'


def test_parse_as_validates():
    assert parse_as(Point, 'ok {"x": 3, "y": 4}').x == 3
    with pytest.raises(AgentOutputError):
        parse_as(Point, '{"x": "not-an-int-at-all", "y": []}')
    with pytest.raises(AgentOutputError):
        parse_as(Point, "no json here")

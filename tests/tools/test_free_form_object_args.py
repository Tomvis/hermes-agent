"""HERMES-23: a nested free-form object (additionalProperties, no properties) must not gain
``properties: {}`` -- gpt-5.x then emits ``{}`` for it (MA's call_tool ``arguments``)."""

from tools.mcp_tool_schema import _normalize_mcp_input_schema
from tools.schema_sanitizer import sanitize_tool_schemas

CALL_TOOL = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name"],
    "properties": {
        "name": {"type": "string"},
        "arguments": {
            "anyOf": [{"type": "object", "additionalProperties": True}, {"type": "null"}],
            "default": None,
        },
        "options": {"type": "object", "properties": {"a": {"type": "string"}}},
        "closed": {"type": "object", "additionalProperties": False},
    },
}


def _args(schema):
    return schema["properties"]["arguments"]


def test_mcp_normalize_keeps_free_form_object_open():
    out = _normalize_mcp_input_schema(CALL_TOOL)
    args = _args(out)
    assert args["type"] == "object" and args["additionalProperties"] is True
    assert "properties" not in args
    assert args["required"] == []
    # Typed and closed objects still get the strict-proxy shape.
    assert out["properties"]["options"]["required"] == []
    assert out["properties"]["closed"]["properties"] == {}
    assert out["properties"] and out["required"] == ["name"]


def test_sanitizer_keeps_free_form_object_open():
    normalized = _normalize_mcp_input_schema(CALL_TOOL)
    tool = {"type": "function", "function": {"name": "t", "parameters": normalized}}
    params = sanitize_tool_schemas([tool])[0]["function"]["parameters"]
    assert "properties" not in _args(params)
    assert _args(params)["required"] == []
    assert params["properties"]["closed"]["properties"] == {}


def test_top_level_free_form_still_gets_properties():
    out = _normalize_mcp_input_schema({"type": "object", "additionalProperties": True})
    assert out["properties"] == {}
    tool = {"type": "function", "function": {"name": "t", "parameters": {"type": "object", "additionalProperties": True}}}
    assert sanitize_tool_schemas([tool])[0]["function"]["parameters"]["properties"] == {}

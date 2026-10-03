"""mcp_servers.<name>.drop_empty_args: blank optional arguments are omitted before tools/call."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tools import mcp_tool_registration as _registration
from tests.tools.test_mcp_structured_content import (  # noqa: F401 (fixture)
    _FakeCallToolResult, _FakeContentBlock, _patch_mcp_server,
)

_HA_SCHEMA = {"type": "object", "properties": {
    "name": {"type": "string"}, "area": {"type": "string"}, "floor": {"type": "string"},
    "domain": {"type": "array", "items": {"type": "string"}},
    "device_class": {"type": "array", "items": {"type": "string"}},
    "brightness": {"type": "integer"}, "note": {"type": "string"},
}, "required": ["note"]}


def _call(session, drop_empty: bool, args: dict, schema_attr: str = "inputSchema") -> dict:
    session.call_tool = AsyncMock(return_value=_FakeCallToolResult(content=[_FakeContentBlock("ok")]))
    tool = SimpleNamespace(name="HassTurnOff", description="", annotations=None, **{schema_attr: _HA_SCHEMA})
    [cand] = _registration._tool_candidates("test-server", [tool], lambda _n: True, 30.0, drop_empty=drop_empty)
    cand.handler(args)
    return session.call_tool.call_args.kwargs["arguments"]


_SENT = {"name": "Living Room Lights", "area": "", "floor": "", "domain": ["light"],
         "device_class": [], "brightness": 0, "note": ""}


@pytest.mark.parametrize("schema_attr", ["inputSchema", "input_schema"])  # cache stand-in / live mcp>=2.0 Tool
def test_blank_optional_args_dropped(_patch_mcp_server, schema_attr):
    assert _call(_patch_mcp_server, True, dict(_SENT), schema_attr) == {
        "name": "Living Room Lights", "domain": ["light"], "brightness": 0, "note": ""}


def test_off_by_default(_patch_mcp_server):
    assert _call(_patch_mcp_server, False, dict(_SENT)) == _SENT

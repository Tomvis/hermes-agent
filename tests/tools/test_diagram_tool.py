"""h5 (HERMES-54): ``render_mermaid`` turns Mermaid source into a PNG through the operator's Kroki
server (``diagram.render_url``) and hands the gateway a ``MEDIA:`` tag, for chats that cannot render
Mermaid (Telegram). The model supplies only source and title: no URL, no path."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from hermes_constants import get_hermes_home

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


class _Kroki:
    """A tiny local stand-in for Kroki: records requests, answers with a scripted response."""

    def __init__(self):
        self.requests = []
        self.status, self.body, self.headers = 200, PNG, {"Content-Type": "image/png"}
        self.release = threading.Event()
        self.hang = False
        kroki = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                kroki.requests.append(
                    (self.path, dict(self.headers), self.rfile.read(length).decode())
                )
                if kroki.hang:
                    kroki.release.wait(10)
                    return
                self.send_response(kroki.status)
                for key, value in kroki.headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(kroki.body)))
                self.end_headers()
                self.wfile.write(kroki.body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()

    def close(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()


def _configure(url):
    home = get_hermes_home()
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(f"diagram:\n  render_url: {json.dumps(url)}\n")


@pytest.fixture
def kroki():
    server = _Kroki()
    _configure(server.url)
    yield server
    server.close()


def _render(**args):
    from tools.registry import registry
    import tools.diagram_tool

    out = registry.dispatch("render_mermaid", args)
    return json.loads(out) if isinstance(out, str) else out


def _diagram_dir() -> Path:
    return get_hermes_home() / "cache" / "generated" / "diagrams"


def test_renders_png_and_returns_media_tag(kroki):
    out = _render(source="graph TD\n  A --> B", title="Hermes flow")

    assert out["success"] is True
    path = Path(out["path"])
    assert path.parent == _diagram_dir() and path.suffix == ".png"
    assert path.read_bytes() == PNG
    assert out["media"] == f"MEDIA:{path}"
    assert path.name.startswith("hermes-flow_")
    ((req_path, headers, body),) = kroki.requests
    assert req_path == "/mermaid/png"
    assert headers["Content-Type"].startswith("text/plain")
    # Kroki sends a syntax error as a text body only when text/plain comes first in Accept.
    assert headers["Accept"].startswith("text/plain")
    assert body == "graph TD\n  A --> B"


def test_strips_a_mermaid_code_fence(kroki):
    _render(source="```mermaid\ngraph LR\n  a --> b\n```")

    assert kroki.requests[0][2] == "graph LR\n  a --> b"


def test_title_cannot_steer_the_path(kroki):
    out = _render(source="graph LR; a-->b", title="../../etc/passwd")

    path = Path(out["path"])
    assert path.parent == _diagram_dir()
    assert ".." not in path.name and "/" not in path.name


@pytest.mark.parametrize("source", ["", "   \n", None, 42])
def test_rejects_empty_or_non_text_source(kroki, source):
    out = _render(source=source)

    assert "error" in out
    assert kroki.requests == []


def test_rejects_oversized_source_without_a_request(kroki, monkeypatch):
    from tools import diagram_tool

    monkeypatch.setattr(diagram_tool, "MAX_SOURCE_CHARS", 100)
    out = _render(source="graph TD\n" + "  a --> b\n" * 50)

    assert "error" in out and "100" in out["error"]
    assert kroki.requests == []


def test_kroki_error_is_returned_so_the_model_can_fix_the_syntax(kroki):
    kroki.status, kroki.headers = 400, {"Content-Type": "text/plain"}
    kroki.body = b"Error 400: Parse error on line 2: unexpected token"

    out = _render(source="graph TD\n  A -->")

    assert "error" in out and "Parse error on line 2" in out["error"]
    assert not _diagram_dir().exists() or not any(_diagram_dir().iterdir())


def test_an_error_image_body_never_reaches_the_model(kroki):
    kroki.status, kroki.body = 400, PNG

    out = _render(source="graph TD\n  A -->")

    assert "error" in out and "HTTP 400" in out["error"]
    assert "PNG" not in out["error"] and "\ufffd" not in out["error"]


def test_oversized_png_is_refused_and_not_written(kroki, monkeypatch):
    from tools import diagram_tool

    monkeypatch.setattr(diagram_tool, "MAX_PNG_BYTES", 32)
    out = _render(source="graph TD; a-->b")

    assert "error" in out
    assert not _diagram_dir().exists() or not any(_diagram_dir().iterdir())


def test_non_png_response_is_refused(kroki):
    kroki.body = b"<svg/>"

    out = _render(source="graph TD; a-->b")

    assert "error" in out


def test_redirects_are_not_followed(kroki):
    kroki.status, kroki.body = 302, b""
    kroki.headers = {"Location": "http://169.254.169.254/latest/meta-data"}

    out = _render(source="graph TD; a-->b")

    assert "error" in out
    assert len(kroki.requests) == 1


def test_times_out(kroki, monkeypatch):
    from tools import diagram_tool

    monkeypatch.setattr(diagram_tool, "TIMEOUT_S", 0.5)
    kroki.hang = True

    out = _render(source="graph TD; a-->b")

    assert "error" in out


def test_unavailable_without_a_render_url():
    from tools.diagram_tool import check_requirements

    _configure("")
    assert check_requirements() is False
    assert "error" in _render(source="graph TD; a-->b")


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://kroki:21", "kroki:8000", "http://"])
def test_only_http_render_urls_count(url):
    from tools.diagram_tool import check_requirements

    _configure(url)
    assert check_requirements() is False


def test_available_with_a_render_url(kroki):
    from tools.diagram_tool import check_requirements

    assert check_requirements() is True


def test_schema_takes_only_source_and_title():
    from tools.diagram_tool import RENDER_MERMAID_SCHEMA

    params = RENDER_MERMAID_SCHEMA["parameters"]
    assert set(params["properties"]) == {"source", "title"}
    assert params["required"] == ["source"]
    assert "Mermaid" in RENDER_MERMAID_SCHEMA["description"]


def test_diagram_toolset_is_opt_in_only():
    from toolsets import _HERMES_CORE_TOOLS, resolve_toolset

    assert resolve_toolset("diagram", include_registry=False) == ["render_mermaid"]
    assert "render_mermaid" not in _HERMES_CORE_TOOLS
    for bundle in ("hermes-cli", "hermes-api-server", "hermes-telegram"):
        assert "render_mermaid" not in resolve_toolset(bundle, include_registry=False)


def test_gateway_auto_attaches_the_png(kroki):
    from gateway.run import _collect_auto_append_media_tags

    result = json.dumps(_render(source="graph TD; a-->b"))
    path = json.loads(result)["path"]
    messages = [
        {"role": "assistant", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "render_mermaid", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": result},
    ]

    tags, voice = _collect_auto_append_media_tags(messages)

    assert tags == [f"MEDIA:{path}"] and voice is False

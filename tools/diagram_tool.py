"""render_mermaid: Mermaid source -> PNG through the operator's Kroki server (h5, HERMES-54).

For chats that cannot render Mermaid themselves (Telegram and other messaging apps); Desktop renders
```mermaid blocks natively and never lists the ``diagram`` toolset. The server comes from config
(``diagram.render_url``, e.g. ``http://kroki:8000``), never from the model, which supplies only the
source and a title. The PNG is written under ``$HERMES_HOME/cache/generated/diagrams/`` and the result
carries a ``MEDIA:`` tag; the gateway auto-attaches it (``_AUTO_APPEND_MEDIA_TOOL_NAMES``).
"""

from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import urlsplit

from tools.registry import registry, tool_error, tool_result

MAX_SOURCE_CHARS = 20_000
MAX_PNG_BYTES = 8 * 1024 * 1024
TIMEOUT_S = 30.0
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_MAX_ERROR_CHARS = 600
_CACHE_KIND = "generated/diagrams"
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/142.0.0.0 Safari/537.36"
)
_FENCE = re.compile(r"^\s*```(?:mermaid)?[ \t]*\n(?P<body>.*?)\n?```\s*$", re.DOTALL | re.IGNORECASE)


def _render_base_url() -> Optional[str]:
    """``diagram.render_url`` when it is an absolute http(s) URL with a host, else None."""
    from hermes_cli.config import cfg_get, load_config_readonly

    url = cfg_get(load_config_readonly(), "diagram", "render_url")
    if not isinstance(url, str) or not url.strip():
        return None
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    return url.strip().rstrip("/")


def check_requirements() -> bool:
    return _render_base_url() is not None


def _slug(title: Any) -> str:
    text = str(title or "").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:40].strip("-")
    return slug or "diagram"


def _clean_source(source: Any) -> Optional[str]:
    if not isinstance(source, str):
        return None
    match = _FENCE.match(source)
    text = (match.group("body") if match else source).strip("\n")
    return text if text.strip() else None


def render_mermaid(source: Any, title: Any = None) -> str:
    base = _render_base_url()
    if base is None:
        return tool_error("Diagram rendering is not configured (diagram.render_url).")
    text = _clean_source(source)
    if text is None:
        return tool_error("source must be non-empty Mermaid text.")
    if len(text) > MAX_SOURCE_CHARS:
        return tool_error(
            f"Mermaid source is {len(text)} characters; the limit is {MAX_SOURCE_CHARS}. Simplify the diagram.")

    import httpx

    try:
        with httpx.Client(timeout=TIMEOUT_S, follow_redirects=False, trust_env=False) as client:
            with client.stream(
                "POST", f"{base}/mermaid/png", content=text.encode("utf-8"),
                # text/plain first: Kroki then sends a syntax error as text, not as an error image.
                headers={"Content-Type": "text/plain; charset=utf-8", "Accept": "text/plain, image/png",
                         "User-Agent": _USER_AGENT},
            ) as response:
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_PNG_BYTES:
                        return tool_error(f"Rendered image exceeds {MAX_PNG_BYTES} bytes. Simplify the diagram.")
                status = response.status_code
    except httpx.TimeoutException:
        return tool_error(f"The diagram renderer did not answer within {TIMEOUT_S:g} s.")
    except httpx.HTTPError as exc:
        return tool_error(f"The diagram renderer is unreachable: {type(exc).__name__}")

    if status != 200:
        raw = bytes(body)
        detail = "" if raw.startswith(PNG_MAGIC) else raw.decode("utf-8", "replace").strip()[:_MAX_ERROR_CHARS]
        return tool_error(f"Rendering failed (HTTP {status}): {detail or 'no detail'}. "
                          "Fix the Mermaid syntax and try again.")
    if not bytes(body).startswith(PNG_MAGIC):
        return tool_error("The diagram renderer returned something other than a PNG.")

    from agent.provider_media import save_bytes

    path = save_bytes(_CACHE_KIND, bytes(body), prefix=_slug(title), extension="png")
    return tool_result(
        success=True, path=str(path), bytes=len(body), media=f"MEDIA:{path}",
        note="The PNG is attached to your reply automatically. Reply with a short caption; "
             "do not repeat the Mermaid source.")


RENDER_MERMAID_SCHEMA = {
    "name": "render_mermaid",
    "description": (
        "Render a Mermaid diagram (flowchart, sequence, class, state, ER, gantt, pie, mindmap, "
        "timeline...) to a PNG image that is attached to your reply. Use it whenever a diagram would "
        "help and this chat cannot display Mermaid code blocks itself (Telegram and other messaging "
        "apps): pass the Mermaid source here instead of writing a ```mermaid block. On an error "
        "(usually Mermaid syntax), fix the source and call it again."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "Mermaid source, without a code fence."},
            "title": {"type": "string", "description": "Short title, used for the file name."},
        },
        "required": ["source"],
    },
}

registry.register(
    name="render_mermaid", toolset="diagram", schema=RENDER_MERMAID_SCHEMA,
    handler=lambda args, **kw: render_mermaid(source=args.get("source"), title=args.get("title")),
    check_fn=check_requirements, emoji="📊", execution_timeout=TIMEOUT_S + 15,
)

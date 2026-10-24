"""h5 (HW-201): ``display.language`` also sets the agent's default reply language and the STT hint.

Upstream ``display.language`` only localizes static UI strings. Here it is the household's home language:
the system prompt gets one line asking for replies in it, and an STT provider without an explicit
``stt.language`` gets it as the hint instead of the seeded ``"en"``. Read fresh (``load_config_readonly``
is cached on the file signature), so a ``hermes config set`` from another process applies to the next
session without a restart. English adds nothing, so an English home keeps a byte-identical prompt.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def home_language(home: Optional[Path] = None) -> Optional[str]:
    """Canonical non-English language id of *home* (default: the ambient profile), else ``None``.
    ``HERMES_LANGUAGE`` wins over ``display.language``, as in ``agent.i18n``."""
    from hermes_constants import get_hermes_home, reset_hermes_home_override, set_hermes_home_override
    token = set_hermes_home_override(home) if home is not None else None
    try:
        from agent.i18n import DEFAULT_LANGUAGE, resolve_language_id
        from agent.secret_scope import UnscopedSecretError, get_secret
        from hermes_cli.config import load_config_readonly
        try:
            lang = get_secret("HERMES_LANGUAGE")
        except UnscopedSecretError:
            import os
            lang = os.environ.get("HERMES_LANGUAGE")
        lang = lang or (load_config_readonly().get("display") or {}).get("language")
        resolved = resolve_language_id(lang, str(get_hermes_home())) if lang else None
    except Exception as exc:
        logger.debug("home language unavailable: %s", exc)
        return None
    finally:
        if token is not None:
            reset_hermes_home_override(token)
    return resolved if resolved and resolved != DEFAULT_LANGUAGE else None


def reply_language_line(home: Optional[Path] = None) -> Optional[str]:
    """System-prompt line for a non-English home, else ``None``."""
    lang = home_language(home)
    if not lang:
        return None
    from agent.i18n_languages import BUNDLED_LANGUAGE_INFO
    name = BUNDLED_LANGUAGE_INFO.get(lang, (lang,))[0]
    return (f"The user's home language is {name} ({lang}). Reply in it unless they write to you "
            "in another language.")


def stt_language_default(configured: Optional[str]) -> Optional[str]:
    """The global STT hint: *configured* (``stt.language``) unless it is the seeded default and neither the
    user's config.yaml nor the managed layer sets it, in which case the home language's base code."""
    try:
        from hermes_cli import managed_scope
        from hermes_cli.config import read_raw_config_readonly
        from hermes_cli.config_defaults import DEFAULT_CONFIG
        if configured != DEFAULT_CONFIG["stt"]["language"]:
            return configured
        if "language" in (read_raw_config_readonly().get("stt") or {}):
            return configured
        if "language" in (managed_scope.load_managed_config().get("stt") or {}):
            return configured
    except Exception as exc:
        logger.debug("stt home language check failed: %s", exc)
        return configured
    lang = home_language()
    return lang.split("-", 1)[0] if lang else configured

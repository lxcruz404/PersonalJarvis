"""The configurable assistant name must flow into the brain system prompt.

User mandate 2026-05-29: renaming the assistant (e.g. to "Micron") must make it
call itself Micron instead of a hardcoded name. These lock that the name reaches
``_build_system_prompt`` — both the base prompt and the prominent identity
directive.

2026-06-29: the persona files were made name-neutral (no baked-in "Jarvis"), so
the identity directive is now emitted for EVERY resolved name except the neutral
``Assistant`` fallback, and it no longer carries the old self-contradictory
"nicht Jarvis" anchor.  # i18n-allow: quotes the literal old system-prompt string
"""
from __future__ import annotations

from jarvis.brain.manager import BrainManager
from jarvis.brain.router import SYSTEM_PROMPT as ROUTER_SYSTEM_PROMPT
from jarvis.core.config import load_config


def _manager_with_name(
    *, wake_phrase: str = "Hey Jarvis", extra: str = "ROUTER DISCIPLINE BLOCK"
) -> BrainManager:
    """A BrainManager with __init__ bypassed — only the attrs the prompt needs."""
    m = BrainManager.__new__(BrainManager)
    m._soul = None
    m._user_profile = None
    m._people = None
    m._core_memory = None
    m._system_prompt_extra = extra
    m._wiki_context_suffix = ""
    m._reply_language = "auto"
    cfg = load_config()
    cfg.performance.cache_optimized_prompt = False
    cfg.trigger.wake_word.phrase = wake_phrase
    m._config = cfg
    return m


def test_wake_jarvis_gets_identity_directive_without_contradiction() -> None:
    prompt = _manager_with_name(wake_phrase="Hey Jarvis")._build_system_prompt()
    assert "Du bist Jarvis" in prompt
    # The persona is now name-neutral, so even a user-chosen "Jarvis" wake word
    # gets a clean identity directive — never the old "Du heisst Jarvis — nicht  # i18n-allow: quotes the literal old system-prompt string
    # Jarvis" self-contradiction.  # i18n-allow: quotes the literal old system-prompt string
    assert "YOUR NAME IS JARVIS" in prompt
    assert "nicht Jarvis" not in prompt  # i18n-allow: literal system-prompt string matched in logic


def test_wake_phrase_micron_makes_assistant_micron() -> None:
    prompt = _manager_with_name(wake_phrase="Micron")._build_system_prompt()
    assert "Du bist Micron" in prompt
    assert "YOUR NAME IS MICRON" in prompt
    assert "nicht Jarvis" not in prompt  # i18n-allow: literal system-prompt string matched in logic


def test_wake_phrase_is_the_only_name_source() -> None:
    # "Hey Computer" wake → the assistant is "Computer".
    prompt = _manager_with_name(wake_phrase="Hey Computer")._build_system_prompt()
    assert "Du bist Computer" in prompt
    assert "YOUR NAME IS COMPUTER" in prompt
    assert "nicht Jarvis" not in prompt  # i18n-allow: literal system-prompt string matched in logic


def test_router_prompt_names_neither_the_assistant_nor_the_user() -> None:
    # The live router tier appends ROUTER_SYSTEM_PROMPT verbatim
    # (brain/factory.py). It used to open with a hardcoded assistant name and
    # call the user by the maintainer's name, so a renamed assistant was told
    # two names and every user was addressed as someone else.
    prompt = _manager_with_name(
        wake_phrase="Oye Darío", extra=ROUTER_SYSTEM_PROMPT
    )._build_system_prompt()
    assert "Du bist Darío" in prompt
    assert "Du bist Jarvis" not in prompt
    assert "Ruben" not in prompt
    assert "Dispatcher" in ROUTER_SYSTEM_PROMPT

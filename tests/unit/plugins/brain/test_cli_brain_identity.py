"""Subscription-CLI brains answer under the name the user gave the assistant.

The CLI brains flatten a turn into one short prompt and drop the router system
prompt, which is where the identity sentence lives. They used to open with a
hardcoded "You are Jarvis", so an assistant the user had named (say, "Darío"
through the wake word) introduced itself as Jarvis on these brains only.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from jarvis.brain.identity import name_directive
from jarvis.core.protocols import BrainMessage, BrainRequest
from jarvis.plugins.brain.antigravity import _build_cli_prompt as antigravity_prompt
from jarvis.plugins.brain.claude_cli import ClaudeCliBrain
from jarvis.plugins.brain.codex import _build_cli_prompt as codex_prompt


def _claude_prompt(req: BrainRequest) -> str:
    return ClaudeCliBrain(structured_prompts=False).build_invocation(req)[1]


BUILDERS: dict[str, Callable[[BrainRequest], str]] = {
    "claude-cli": _claude_prompt,
    "antigravity": antigravity_prompt,
    "codex": codex_prompt,
}


def _req(system: str) -> BrainRequest:
    return BrainRequest(
        messages=(BrainMessage(role="user", content="¿Cómo te llamas?"),),
        system=system,
    )


@pytest.mark.parametrize("brain", sorted(BUILDERS))
def test_a_named_assistant_keeps_its_name(brain: str) -> None:
    system = f"{name_directive('Darío')}\n\nROUTER PROMPT WITH TOOLS"
    prompt = BUILDERS[brain](_req(system))
    assert prompt.startswith("YOUR NAME IS DARÍO.")
    assert "You are Darío" in prompt
    assert "You are Jarvis" not in prompt
    assert "ROUTER PROMPT WITH TOOLS" not in prompt


@pytest.mark.parametrize("brain", sorted(BUILDERS))
def test_an_unnamed_assistant_gets_no_invented_name(brain: str) -> None:
    prompt = BUILDERS[brain](_req("ROUTER PROMPT WITH TOOLS"))
    assert "YOUR NAME IS" not in prompt
    assert "Jarvis" not in prompt
    assert "¿Cómo te llamas?" in prompt

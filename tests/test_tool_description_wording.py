# tests/test_tool_description_wording.py
"""
Regression test for the "gpt-4o declines tool calls over credential wording"
bug: model-facing tool descriptions must not phrase env-var mentions as a
precondition (e.g. "Requires X") that the model feels obligated to verify
before calling the tool.
"""

from __future__ import annotations

import asyncio
import re

from openosint.agent import SYSTEM_PROMPT, TOOL_DEFINITIONS
from openosint.mcp_server import list_tools

# Matches "Requires FOO_BAR" / "requires FOO_BAR and BAZ_QUX" style preconditions,
# but not unrelated uses of "requires" (e.g. "requires the 'graph' extra").
# Only "requires" is case-insensitive; the env-var name must be UPPER_SNAKE_CASE.
_PRECONDITION_RE = re.compile(r"(?i:requires)\s+[A-Z][A-Z0-9_]*")


def test_agent_tool_definitions_have_no_credential_precondition_wording():
    for tool in TOOL_DEFINITIONS:
        description = tool["description"]
        assert not _PRECONDITION_RE.search(description), (
            f"{tool['name']!r} description reads as a credential precondition: {description!r}"
        )


def test_mcp_server_tool_descriptions_have_no_credential_precondition_wording():
    tools = asyncio.run(list_tools())
    for tool in tools:
        assert not _PRECONDITION_RE.search(tool.description), (
            f"{tool.name!r} description reads as a credential precondition: {tool.description!r}"
        )


def test_system_prompt_tells_model_not_to_ask_for_credentials():
    prompt = SYSTEM_PROMPT.lower()
    assert "credential" in prompt or "api key" in prompt
    assert "never ask" in prompt or "don't ask" in prompt

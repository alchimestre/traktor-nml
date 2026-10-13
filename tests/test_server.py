"""The MCP surface, exercised in process: the three tools exist under the names a session will see, and each
returns what the command line prints — `plan` without writing, `apply` with."""

from __future__ import annotations

import asyncio

from test_cli import config_file, config_for
from test_sync import entry_for, lane, moved

from traktor_nml import server as server_module


def call(server, name: str) -> str:
    """One tool call, as text: the same path a session's call takes, without a transport."""
    result = asyncio.run(server.call_tool(name, {}))
    return "".join(getattr(block, "text", "") for block in result.content)


def test_the_server_offers_exactly_the_three_verbs(tmp_path):
    settings = config_for(tmp_path, entries="")
    server = server_module.build(settings)
    assert {tool.name for tool in asyncio.run(server.list_tools())} == {"status", "plan", "apply", "purge"}


def test_plan_reads_and_apply_writes_through_the_server(tmp_path):
    was = lane(tmp_path, "Kiasmas - Blurred.mp3", where="lossy")
    settings = config_for(tmp_path, entries=entry_for(was),
                          run=(was, lane(tmp_path, "Kiasmas - Blurred.aiff")))
    config_file(tmp_path, settings)          # the server reads its own config, so this must exist
    moved(tmp_path, "Kiasmas - Blurred.aiff")
    before = settings.collection.read_bytes()
    server = server_module.build(settings)

    assert "1 to repoint" in call(server, "plan")
    assert settings.collection.read_bytes() == before, "plan must not write"

    assert "backed up to" in call(server, "apply")
    assert settings.collection.read_bytes() != before
    assert "0 to repoint" in call(server, "plan")
    assert "entries" in call(server, "status")


def test_apply_through_the_server_on_a_settled_collection_says_nothing_to_write(tmp_path):
    settings = config_for(tmp_path, entries="")
    server = server_module.build(settings)
    assert "nothing to write" in call(server, "apply")

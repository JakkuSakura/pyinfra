from __future__ import annotations

import asyncio

from pyinfra.api import Config, State
from pyinfra.api.state import StateStage
from pyinfra.async_context import AsyncContext
from pyinfra.facts.server import Command
from pyinfra.operations import server

from .util import make_inventory


def test_async_context_operation(fake_asyncssh):
    async def _run():
        inventory = make_inventory()
        state = State(inventory, Config())

        async with AsyncContext(state):
            results = await server.shell("echo async-context")

            assert set(results.keys()) == {
                inventory.get_host("somehost"),
                inventory.get_host("anotherhost"),
            }
            assert all(meta is not None for meta in results.values())
            assert state.current_stage == StateStage.Execute

            for connection in fake_asyncssh.values():
                assert any("echo async-context" in command for command in connection.commands_run)

        assert state.current_stage == StateStage.Disconnect
        for connection in fake_asyncssh.values():
            assert connection._closed is True

    asyncio.run(_run())


def test_async_context_fact(fake_asyncssh):
    async def _run():
        inventory = make_inventory()
        state = State(inventory, Config())

        async with AsyncContext(state) as ctx:
            for connection in fake_asyncssh.values():
                connection.command_results["echo fact-value"] = {
                    "stdout": "value\n",
                    "stderr": "",
                    "exit_status": 0,
                }

            facts = await ctx.get_fact(Command, "echo fact-value")

            assert set(facts.keys()) == {
                inventory.get_host("somehost"),
                inventory.get_host("anotherhost"),
            }

            for value in facts.values():
                assert value == "value"

        assert state.current_stage == StateStage.Disconnect
        for connection in fake_asyncssh.values():
            assert connection._closed is True

    asyncio.run(_run())


def test_async_context_hosts_subset(fake_asyncssh):
    async def _run():
        inventory = make_inventory()
        state = State(inventory, Config())

        specific = inventory.get_host("somehost")
        async with AsyncContext(state, hosts=[specific]):
            await server.shell("echo subset")

            assert any(
                "echo subset" in command for command in fake_asyncssh["somehost"].commands_run
            )
            assert "anotherhost" not in fake_asyncssh

        assert state.current_stage == StateStage.Disconnect
        assert fake_asyncssh["somehost"]._closed is True

    asyncio.run(_run())

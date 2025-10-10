from __future__ import annotations

import asyncio

from pyinfra.api import Config, State
from pyinfra.api.connect import connect_all_async, disconnect_all_async
from pyinfra.api.state import StateStage
from pyinfra.async_context import AsyncContext
from pyinfra.facts.server import Command
from pyinfra.operations import server

from .util import make_inventory


def test_async_context_operation(fake_asyncssh):
    async def _run():
        inventory = make_inventory()
        state = State(inventory, Config())

        await connect_all_async(state)

        ctx = AsyncContext(state)
        results = await ctx.run_operation(server.shell, "echo async-context")

        assert set(results.keys()) == {inventory.get_host("somehost"), inventory.get_host("anotherhost")}
        assert all(meta is not None for meta in results.values())
        assert state.current_stage == StateStage.Execute

        for connection in fake_asyncssh.values():
            assert any("echo async-context" in command for command in connection.commands_run)

        await disconnect_all_async(state)

    asyncio.run(_run())


def test_async_context_fact(fake_asyncssh):
    async def _run():
        inventory = make_inventory()
        state = State(inventory, Config())

        await connect_all_async(state)

        for connection in fake_asyncssh.values():
            connection.command_results["echo fact-value"] = {
                "stdout": "value\n",
                "stderr": "",
                "exit_status": 0,
            }

        ctx = AsyncContext(state)
        facts = await ctx.get_fact(Command, "echo fact-value")

        assert set(facts.keys()) == {inventory.get_host("somehost"), inventory.get_host("anotherhost")}

        for value in facts.values():
            assert value == "value"

        await disconnect_all_async(state)

    asyncio.run(_run())


def test_async_context_hosts_subset(fake_asyncssh):
    async def _run():
        inventory = make_inventory()
        state = State(inventory, Config())

        await connect_all_async(state)

        specific = inventory.get_host("somehost")
        ctx = AsyncContext(state, hosts=[specific])
        await ctx.run_operation(server.shell, "echo subset")

        assert any(
            "echo subset" in command for command in fake_asyncssh["somehost"].commands_run
        )
        assert all(
            "echo subset" not in command for command in fake_asyncssh["anotherhost"].commands_run
        )

        await disconnect_all_async(state)

    asyncio.run(_run())

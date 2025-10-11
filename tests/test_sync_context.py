from __future__ import annotations

from pyinfra.api import Config, State
from pyinfra.api.state import StateStage
from pyinfra.facts.server import Command
from pyinfra.operations import files, server
from pyinfra.sync_context import SyncContext

from .util import make_inventory


def test_sync_context_operation(fake_asyncssh):
    inventory = make_inventory()
    state = State(inventory, Config())

    with SyncContext(state):
        results = server.shell("echo sync-context")

        assert set(results.keys()) == {
            inventory.get_host("somehost"),
            inventory.get_host("anotherhost"),
        }
        assert all(meta is not None for meta in results.values())
        assert state.current_stage == StateStage.Execute

        for connection in fake_asyncssh.values():
            assert any("echo sync-context" in command for command in connection.commands_run)

    assert state.current_stage == StateStage.Disconnect
    for connection in fake_asyncssh.values():
        assert connection._closed is True


def test_sync_context_fact(fake_asyncssh):
    inventory = make_inventory()
    state = State(inventory, Config())

    with SyncContext(state) as ctx:
        for connection in fake_asyncssh.values():
            connection.command_results["echo fact-value"] = {
                "stdout": "value\n",
                "stderr": "",
                "exit_status": 0,
            }

        facts = ctx.get_fact(Command, "echo fact-value")

        assert set(facts.keys()) == {
            inventory.get_host("somehost"),
            inventory.get_host("anotherhost"),
        }

        for value in facts.values():
            assert value == "value"

    assert state.current_stage == StateStage.Disconnect
    for connection in fake_asyncssh.values():
        assert connection._closed is True


def test_sync_context_hosts_subset(fake_asyncssh):
    inventory = make_inventory()
    state = State(inventory, Config())

    specific = inventory.get_host("somehost")
    with SyncContext(state, hosts=[specific]):
        server.shell("echo subset")

        assert any("echo subset" in command for command in fake_asyncssh["somehost"].commands_run)
        assert "anotherhost" not in fake_asyncssh

    assert state.current_stage == StateStage.Disconnect
    assert fake_asyncssh["somehost"]._closed is True


def test_sync_context_files_put(fake_asyncssh, tmp_path):
    inventory = make_inventory()
    state = State(inventory, Config())

    local_file = tmp_path / "sync-context.txt"
    local_file.write_text("sync context test")

    with SyncContext(state):
        results = files.put(src=str(local_file), dest="/sync-context.txt")

        assert set(results.keys()) == {
            inventory.get_host("somehost"),
            inventory.get_host("anotherhost"),
        }

    assert state.current_stage == StateStage.Disconnect

from __future__ import annotations

from pyinfra.api import Config, State, deploy
from pyinfra.api.state import StateStage
from pyinfra.facts.server import Command
from pyinfra.operations import files, server
from pyinfra.sync_context import SyncContext, SyncHostContext

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

    with SyncContext(state):
        for connection in fake_asyncssh.values():
            connection.command_results["echo fact-value"] = {
                "stdout": "value\n",
                "stderr": "",
                "exit_status": 0,
            }

        facts = {}
        for hostname in ("somehost", "anotherhost"):
            host = inventory.get_host(hostname)
            facts[host] = host.get_fact(Command, "echo fact-value")

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


def test_sync_host_context_limits_to_single_host(fake_asyncssh):
    inventory = make_inventory()
    state = State(inventory, Config())

    with SyncHostContext(state, "somehost"):
        results = server.shell("echo sync-host-context")

        somehost = inventory.get_host("somehost")
        assert set(results.keys()) == {somehost}
        assert set(fake_asyncssh.keys()) == {"somehost"}

        fake_asyncssh["somehost"].command_results["echo sync-host-fact"] = {
            "stdout": "value\n",
            "stderr": "",
            "exit_status": 0,
        }

        fact_value = somehost.get_fact(Command, "echo sync-host-fact")
        assert fact_value == "value"

        @deploy("Sync host deploy")
        def sample_host_deploy():
            server.shell(name="Sync host deploy op", commands="echo sync-host-deploy")

        sample_host_deploy()
        assert any(
            "echo sync-host-deploy" in command for command in fake_asyncssh["somehost"].commands_run
        )

    assert fake_asyncssh["somehost"]._closed is True
    assert "anotherhost" not in fake_asyncssh


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


def test_sync_context_run_deploy(fake_asyncssh):
    inventory = make_inventory()
    state = State(inventory, Config())

    @deploy("Sync context deploy")
    def sample_deploy():
        server.shell(name="Sync deploy op", commands="echo sync-context-deploy")

    with SyncContext(state):
        sample_deploy()

        for hostname, connection in fake_asyncssh.items():
            assert hostname in {"somehost", "anotherhost"}
            assert any("echo sync-context-deploy" in command for command in connection.commands_run)

    fake_asyncssh.clear()

    with SyncContext(state, hosts=[inventory.get_host("somehost")]):
        sample_deploy(hosts=[inventory.get_host("somehost")])

        assert set(fake_asyncssh.keys()) == {"somehost"}
        assert any(
            "echo sync-context-deploy" in command
            for command in fake_asyncssh["somehost"].commands_run
        )

    assert all(connection._closed for connection in fake_asyncssh.values())
    fake_asyncssh.clear()

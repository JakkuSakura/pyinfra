from __future__ import annotations

import os
from typing import Dict

import asyncssh

from pyinfra.api import Config, State, StringCommand
from pyinfra.api.connect import connect_all, disconnect_all

from ..util import make_inventory


def test_connect_all_activates_hosts(fake_asyncssh):
    inventory = make_inventory()
    state = State(inventory, Config())

    connect_all(state)

    assert {host.name for host in state.active_hosts} == {"somehost", "anotherhost"}
    assert set(fake_asyncssh.keys()) == {"somehost", "anotherhost"}

    disconnect_all(state)


def test_run_shell_command_uses_asyncssh(fake_asyncssh):
    inventory = make_inventory()
    state = State(inventory, Config())

    connect_all(state)
    host = inventory.get_host("somehost")

    connection = fake_asyncssh[host.name]
    connection.command_results["echo hello"] = {"stdout": "hello\n", "stderr": "", "exit_status": 0}

    status, output = host.run_shell_command(StringCommand("echo", "hello"))

    assert status is True
    assert output.stdout_lines == ["hello"]
    assert any("echo hello" in command for command in connection.commands_run)

    disconnect_all(state)


def test_put_file_uses_scp_protocol(fake_asyncssh, monkeypatch, tmp_path):
    inventory = make_inventory(override_data={"ssh_file_transfer_protocol": "scp"})
    state = State(inventory, Config())

    remote_files: Dict[str, Dict[str, bytes]] = {}

    async def _scp_stub(src, dst, **kwargs):  # type: ignore[override]
        # Upload: local path -> (connection, remote_path)
        if isinstance(dst, tuple):
            client, remote_path = dst
            with open(src, "rb") as src_file:
                data = src_file.read()
            remote_files.setdefault(client.hostname, {})[remote_path] = data
            return

        # Download: (connection, remote_path) -> local path
        client, remote_path = src
        data = remote_files.get(client.hostname, {}).get(remote_path)
        if data is None:
            raise FileNotFoundError(remote_path)
        directory = os.path.dirname(dst)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(dst, "wb") as dest_file:
            dest_file.write(data)

    monkeypatch.setattr(asyncssh, "scp", _scp_stub)

    connect_all(state)
    host = inventory.get_host("somehost")

    local_file = tmp_path / "upload.txt"
    local_file.write_text("hello scp")

    assert host.put_file(str(local_file), "/remote/upload.txt") is True
    assert remote_files["somehost"]["/remote/upload.txt"] == b"hello scp"

    disconnect_all(state)


def test_get_file_uses_scp_protocol(fake_asyncssh, monkeypatch, tmp_path):
    inventory = make_inventory(override_data={"ssh_file_transfer_protocol": "scp"})
    state = State(inventory, Config())

    remote_files: Dict[str, Dict[str, bytes]] = {"somehost": {"/remote/file.txt": b"from-remote"}}

    async def _scp_stub(src, dst, **kwargs):  # type: ignore[override]
        if isinstance(dst, tuple):
            client, remote_path = dst
            with open(src, "rb") as src_file:
                data = src_file.read()
            remote_files.setdefault(client.hostname, {})[remote_path] = data
            return

        client, remote_path = src
        data = remote_files.get(client.hostname, {}).get(remote_path)
        if data is None:
            raise FileNotFoundError(remote_path)
        directory = os.path.dirname(dst)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(dst, "wb") as dest_file:
            dest_file.write(data)

    monkeypatch.setattr(asyncssh, "scp", _scp_stub)

    connect_all(state)
    host = inventory.get_host("somehost")

    destination = tmp_path / "download.txt"
    assert host.get_file("/remote/file.txt", str(destination)) is True
    assert destination.read_text() == "from-remote"

    disconnect_all(state)

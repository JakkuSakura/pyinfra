from __future__ import annotations

from pathlib import Path

from pyinfra import inventory
from pyinfra.context import ctx_inventory, ctx_state

from .util import run_cli


TEST_CLI_DIR = Path(__file__).resolve().parent
DEPLOY_DIR = TEST_CLI_DIR / "deploy"
INVALID_INVENTORY = TEST_CLI_DIR / "inventories" / "invalid.py"


def _reset_contexts() -> None:
    ctx_state.reset()
    ctx_inventory.reset()


def _patch_sync_executor(monkeypatch):
    async def _run_in_executor_sync(self, func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(
        "pyinfra.api.state.State.run_in_executor",
        _run_in_executor_sync,
        raising=False,
    )


def test_load_deploy_group_data(fake_asyncssh, monkeypatch):
    _patch_sync_executor(monkeypatch)
    fake_asyncssh.clear()

    try:
        hosts = ["somehost", "anotherhost", "someotherhost"]
        result = run_cli(
            "-y",
            "--parallel=1",
            ",".join(hosts),
            str(DEPLOY_DIR / "deploy.py"),
            f"--chdir={DEPLOY_DIR}",
        )
        assert result.exit_code == 0, result.stdout

        assert inventory.data.get("hello") == "world"
        assert "leftover_data" in inventory.group_data
        group_data = inventory.group_data["leftover_data"]
        assert group_data.get("still_parsed") == "never_used"
        assert group_data.get("_global_arg") == "gets_parsed"
    finally:
        _reset_contexts()


def test_load_group_data(fake_asyncssh, monkeypatch):
    _patch_sync_executor(monkeypatch)
    fake_asyncssh.clear()

    try:
        hosts = ["somehost", "anotherhost", "someotherhost"]
        result = run_cli(
            "-y",
            "--parallel=1",
            ",".join(hosts),
            f"--group-data={DEPLOY_DIR / 'group_data'}",
            "exec",
            "uptime",
        )
        assert result.exit_code == 0, result.stdout

        assert inventory.data.get("hello") == "world"
        assert "leftover_data" in inventory.group_data
        group_data = inventory.group_data["leftover_data"]
        assert group_data.get("still_parsed") == "never_used"
        assert group_data.get("_global_arg") == "gets_parsed"
    finally:
        _reset_contexts()


def test_load_group_data_file(fake_asyncssh, monkeypatch):
    _patch_sync_executor(monkeypatch)
    fake_asyncssh.clear()

    try:
        hosts = ["somehost", "anotherhost", "someotherhost"]
        filename = DEPLOY_DIR / "group_data" / "leftover_data.py"
        result = run_cli(
            "-y",
            "--parallel=1",
            ",".join(hosts),
            f"--group-data={filename}",
            "exec",
            "uptime",
        )
        assert result.exit_code == 0, result.stdout

        assert "hello" not in inventory.data
        assert "leftover_data" in inventory.group_data
        group_data = inventory.group_data["leftover_data"]
        assert group_data.get("still_parsed") == "never_used"
        assert group_data.get("_global_arg") == "gets_parsed"
    finally:
        _reset_contexts()


def test_ignores_variables_with_leading_underscore(fake_asyncssh, monkeypatch):
    _patch_sync_executor(monkeypatch)
    fake_asyncssh.clear()

    try:
        result = run_cli(
            "--parallel=1",
            str(INVALID_INVENTORY),
            "exec",
            "--debug",
            "--",
            "echo hi",
        )

        assert result.exit_code == 0, result.stdout
        assert (
            'Ignoring variable "_hosts" in inventory file since it starts with a leading underscore'
            in result.stderr
        )
        assert inventory.hosts == {}
    finally:
        _reset_contexts()


def test_only_supports_list_and_tuples(fake_asyncssh, monkeypatch):
    _patch_sync_executor(monkeypatch)
    fake_asyncssh.clear()

    try:
        result = run_cli(
            "--parallel=1",
            str(INVALID_INVENTORY),
            "exec",
            "--debug",
            "--",
            "echo hi",
        )

        assert result.exit_code == 0, result.stdout
        assert 'Ignoring variable "dict_hosts" in inventory file' in result.stderr
        assert 'Ignoring variable "generator_hosts" in inventory file' in result.stderr
        assert inventory.hosts == {}
    finally:
        _reset_contexts()


def test_host_groups_may_only_contain_strings_or_tuples(fake_asyncssh, monkeypatch):
    _patch_sync_executor(monkeypatch)
    fake_asyncssh.clear()

    try:
        result = run_cli(
            "--parallel=1",
            str(INVALID_INVENTORY),
            "exec",
            "--",
            "echo hi",
        )

        assert result.exit_code == 0, result.stdout
        assert 'Ignoring host group "issue_662"' in result.stderr
        assert inventory.hosts == {}
    finally:
        _reset_contexts()

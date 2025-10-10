from __future__ import annotations

import asyncio
import os
import random
import shlex
import tempfile
from dataclasses import dataclass
from threading import Event, Thread
from typing import IO, TYPE_CHECKING, Any, Iterable, Optional, Protocol

from socket import timeout as timeout_error

import asyncssh
import click
import pyinfra
from typing_extensions import TypedDict, Unpack, override

from pyinfra import logger
from pyinfra.api.command import QuoteString, StringCommand
from pyinfra.api.exceptions import ConnectError, PyinfraError
from pyinfra.api.util import get_file_io, memoize

from .base import BaseConnector, DataMeta
from .util import (
    CommandOutput,
    OutputLine,
    execute_command_with_sudo_retry,
    make_unix_command_for_host,
    run_local_process,
)

if TYPE_CHECKING:
    from pyinfra.api.arguments import ConnectorArguments
    from pyinfra.api.host import Host
    from pyinfra.api.state import State


class ConnectorData(TypedDict):
    ssh_hostname: str
    ssh_port: int
    ssh_user: str
    ssh_password: str
    ssh_key: str
    ssh_key_password: str

    ssh_allow_agent: bool
    ssh_look_for_keys: bool
    ssh_forward_agent: bool

    ssh_config_file: str
    ssh_known_hosts_file: str
    ssh_strict_host_key_checking: str

    ssh_paramiko_connect_kwargs: dict  # backward compatibility name

    ssh_connect_retries: int
    ssh_connect_retry_min_delay: float
    ssh_connect_retry_max_delay: float
    ssh_file_transfer_protocol: str


connector_data_meta: dict[str, DataMeta] = {
    "ssh_hostname": DataMeta("SSH hostname"),
    "ssh_port": DataMeta("SSH port"),
    "ssh_user": DataMeta("SSH user"),
    "ssh_password": DataMeta("SSH password"),
    "ssh_key": DataMeta("SSH key filename"),
    "ssh_key_password": DataMeta("SSH key password"),
    "ssh_allow_agent": DataMeta("Whether to use any active SSH agent", True),
    "ssh_look_for_keys": DataMeta("Whether to look for private keys", True),
    "ssh_forward_agent": DataMeta("Whether to enable SSH forward agent", False),
    "ssh_config_file": DataMeta("SSH config filename"),
    "ssh_known_hosts_file": DataMeta("SSH known_hosts filename"),
    "ssh_strict_host_key_checking": DataMeta(
        "SSH strict host key checking",
        "accept-new",
    ),
    "ssh_paramiko_connect_kwargs": DataMeta(
        "Override keyword arguments passed into asyncssh.connect",
    ),
    "ssh_connect_retries": DataMeta("Number of tries to connect via ssh", 0),
    "ssh_connect_retry_min_delay": DataMeta(
        "Lower bound for random delay between retries",
        0.1,
    ),
    "ssh_connect_retry_max_delay": DataMeta(
        "Upper bound for random delay between retries",
        0.5,
    ),
    "ssh_file_transfer_protocol": DataMeta(
        "Protocol to use for file transfers. Can be ``sftp``.",
        "sftp",
    ),
}


class FileTransferClient(Protocol):
    def getfo(self, remote_filename: str, fl: IO) -> Any | None:
        ...

    def putfo(self, fl: IO, remote_filename: str) -> Any | None:
        ...


def _format_known_host(hostname: str, port: Optional[int]) -> str:
    if port and port != 22:
        return f"[{hostname}]:{port}"
    return hostname


def _normalise_stdin(stdin: Any) -> Optional[str]:
    if stdin is None:
        return None
    if isinstance(stdin, (bytes, str)):
        return stdin.decode() if isinstance(stdin, bytes) else stdin
    if isinstance(stdin, Iterable):
        return "".join(str(item) for item in stdin)
    return str(stdin)


class _SFTPWrapper:
    def __init__(self, connector: "SSHConnector") -> None:
        self._connector = connector

    def getfo(self, remote_filename: str, fl: IO) -> None:
        data = self._connector._submit(self._connector._async_read_file(remote_filename))
        fl.write(data)

    def putfo(self, fl: IO, remote_filename: str) -> None:
        position = fl.tell()
        fl.seek(0)
        data = fl.read()
        fl.seek(position)
        if isinstance(data, str):
            data = data.encode()
        self._connector._submit(self._connector._async_write_file(remote_filename, data))


class _SCPWrapper:
    def __init__(self, connector: "SSHConnector") -> None:
        self._connector = connector

    def getfo(self, remote_filename: str, fl: IO) -> None:
        data = self._connector._submit(
            self._connector._async_scp_download(remote_filename)
        )
        fl.write(data)

    def putfo(self, fl: IO, remote_filename: str) -> None:
        position = fl.tell() if hasattr(fl, "tell") else None
        if hasattr(fl, "seek"):
            fl.seek(0)
        data = fl.read()
        if position is not None and hasattr(fl, "seek"):
            fl.seek(position)
        if isinstance(data, str):
            data = data.encode()
        self._connector._submit(self._connector._async_scp_upload(remote_filename, data))


class SSHConnector(BaseConnector):
    handles_execution = True

    data_cls = ConnectorData
    data_meta = connector_data_meta
    data: ConnectorData

    def __init__(self, state: "State", host: "Host"):
        super().__init__(state, host)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: Thread | None = None
        self._loop_ready: Event | None = None
        self._connection: asyncssh.SSHClientConnection | None = None
        self._sftp_client: asyncssh.SFTPClient | None = None
        self._known_hosts_file: str | None = None
        self._strict_host_key_checking: str = self.data["ssh_strict_host_key_checking"] or "accept-new"
        self._transfer_protocol = (
            self.data.get("ssh_file_transfer_protocol") or "sftp"
        ).lower()

    @override
    @staticmethod
    def make_names_data(name):
        yield f"@ssh/{name}", {"ssh_hostname": name}, []

    # Event loop helpers

    def _ensure_loop(self) -> None:
        if self._loop is not None:
            return

        self._loop = asyncio.new_event_loop()
        self._loop_ready = Event()

        def _run_loop() -> None:
            assert self._loop is not None
            asyncio.set_event_loop(self._loop)
            assert self._loop_ready is not None
            self._loop_ready.set()
            self._loop.run_forever()

        self._loop_thread = Thread(target=_run_loop, daemon=True)
        self._loop_thread.start()
        assert self._loop_ready is not None
        self._loop_ready.wait()

    def _submit(self, coro: asyncio.Future | asyncio.coroutines.Coroutine) -> Any:
        self._ensure_loop()
        assert self._loop is not None
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()

    # Connection management

    def _build_connect_kwargs(self, hostname: str) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "username": self.data["ssh_user"] or None,
            "port": int(self.data["ssh_port"]) if self.data["ssh_port"] else None,
            "password": self.data["ssh_password"] or None,
            "agent_forwarding": self.data["ssh_forward_agent"],
            "login_timeout": self.state.config.CONNECT_TIMEOUT,
        }

        ssh_key = self.data["ssh_key"]
        ssh_key_password = self.data["ssh_key_password"]

        if ssh_key:
            key = self._load_private_key(ssh_key, ssh_key_password)
            kwargs["client_keys"] = [key]
        elif not self.data["ssh_look_for_keys"]:
            kwargs["client_keys"] = []

        if not self.data["ssh_allow_agent"]:
            kwargs["agent_path"] = ()

        ssh_config_file = self.data["ssh_config_file"]
        if ssh_config_file:
            try:
                kwargs["config"] = asyncssh.read_ssh_config(ssh_config_file)
            except FileNotFoundError:
                raise ConnectError(f"SSH config file not found: {ssh_config_file}")

        self._known_hosts_file = self.data["ssh_known_hosts_file"] or None

        strict_setting = (self.data["ssh_strict_host_key_checking"] or "accept-new").lower()
        if strict_setting in {"no", "off"}:
            kwargs["known_hosts"] = None
        elif strict_setting == "accept-new":
            if self._known_hosts_file and os.path.isfile(self._known_hosts_file):
                kwargs["known_hosts"] = self._known_hosts_file
            else:
                kwargs["known_hosts"] = None
        else:  # "yes" / default strict
            kwargs["known_hosts"] = self._known_hosts_file or None

        extra_kwargs = self.data.get("ssh_paramiko_connect_kwargs") or {}
        kwargs.update(extra_kwargs)

        if kwargs.get("port") is None:
            kwargs.pop("port")

        return kwargs

    def _load_private_key(self, key_filename: str, key_password: str) -> asyncssh.SSHKey:
        if key_filename in self.state.private_keys:
            return self.state.private_keys[key_filename]

        candidate_paths = []
        if self.state.cwd:
            candidate_paths.append(os.path.join(self.state.cwd, key_filename))
        candidate_paths.append(os.path.expanduser(key_filename))

        for filename in candidate_paths:
            if not os.path.isfile(filename):
                continue

            passphrase = key_password

            while True:
                try:
                    key = asyncssh.read_private_key(filename, passphrase=passphrase)
                    self.state.private_keys[key_filename] = key
                    return key
                except asyncssh.KeyImportError as exc:  # encrypted key without passphrase
                    if "encrypted" not in str(exc).lower():
                        break

                    if passphrase:
                        break

                    if pyinfra.is_cli:
                        passphrase = click.prompt(
                            f"Enter password for private key: {key_filename}",
                            hide_input=True,
                        )
                    else:
                        raise PyinfraError(
                            "Private key file ({0}) is encrypted, set ssh_key_password to use this key".format(
                                key_filename,
                            ),
                        )

        raise PyinfraError(f"No such private key file: {key_filename}")

    def connect(self) -> None:
        hostname = self.data["ssh_hostname"] or self.host.name
        if self._transfer_protocol not in {"sftp", "scp"}:
            raise ConnectError(
                f"Unsupported file transfer protocol: {self._transfer_protocol}"
            )
        kwargs = self._build_connect_kwargs(hostname)
        logger.debug("Connecting to: %s (%r)", hostname, kwargs)

        try:
            self._connection = self._submit(self._async_connect(hostname, kwargs))
        except (asyncssh.Error, OSError) as exc:
            raise ConnectError(f"SSH error connecting to {hostname}: {exc}")

    async def _async_connect(self, hostname: str, kwargs: dict[str, Any]) -> asyncssh.SSHClientConnection:
        retries = self.data["ssh_connect_retries"]
        delay_min = self.data["ssh_connect_retry_min_delay"]
        delay_max = self.data["ssh_connect_retry_max_delay"]

        attempt = 0
        while True:
            try:
                connection = await asyncssh.connect(hostname, **kwargs)
                strict_setting = (self._strict_host_key_checking or "accept-new").lower()
                if strict_setting == "accept-new" and self._known_hosts_file:
                    await self._store_host_key(connection, hostname, kwargs.get("port"))
                return connection
            except (asyncssh.Error, OSError):
                attempt += 1
                if attempt > retries:
                    raise
                await asyncio.sleep(random.uniform(delay_min, delay_max))

    async def _store_host_key(
        self,
        connection: asyncssh.SSHClientConnection,
        hostname: str,
        port: Optional[int],
    ) -> None:
        if not self._known_hosts_file:
            return

        host_key = connection.get_server_host_key()
        if host_key is None:
            return

        entry_host = _format_known_host(hostname, port)
        export = host_key.export_public_key()
        line = f"{entry_host} {export}\n"

        os.makedirs(os.path.dirname(self._known_hosts_file), exist_ok=True)

        try:
            with open(self._known_hosts_file, "a", encoding="utf-8") as known_hosts:
                known_hosts.write(line)
        except OSError as exc:
            logger.warning("Failed to write host key for %s: %s", entry_host, exc)

    def disconnect(self) -> None:
        if self._connection is None:
            return

        async def _close() -> None:
            if self._sftp_client:
                self._sftp_client.exit()
                self._sftp_client = None
            self._connection.close()
            await self._connection.wait_closed()

        try:
            self._submit(_close())
        finally:
            self._connection = None
            if self._loop and self._loop_thread:
                self._loop.call_soon_threadsafe(self._loop.stop)
                self._loop_thread.join()
            self._loop = None
            self._loop_thread = None
            self._loop_ready = None

    # Command execution

    def run_shell_command(
        self,
        command: StringCommand,
        print_output: bool = False,
        print_input: bool = False,
        **arguments: Unpack["ConnectorArguments"],
    ) -> tuple[bool, CommandOutput]:
        _get_pty = arguments.pop("_get_pty", False)
        _timeout = arguments.pop("_timeout", None)
        _stdin = arguments.pop("_stdin", None)
        _success_exit_codes = arguments.pop("_success_exit_codes", None)

        def execute_command() -> tuple[int, CommandOutput]:
            unix_command = make_unix_command_for_host(self.state, self.host, command, **arguments)
            actual_command = unix_command.get_raw_value()

            logger.debug(
                "Running command on %s: (pty=%s) %s",
                self.host.name,
                _get_pty,
                unix_command,
            )

            if print_input:
                click.echo(f"{self.host.print_prefix}>>> {unix_command}", err=True)

            stdin_value = _normalise_stdin(_stdin)

            try:
                exit_status, combined_output = self._submit(
                    self._async_run_command(
                        actual_command,
                        stdin_value,
                        _get_pty,
                        _timeout,
                        print_output,
                        self.host.print_prefix,
                    ),
                )
            except asyncio.TimeoutError as exc:
                raise timeout_error() from exc

            return exit_status, combined_output

        return_code, combined_output = execute_command_with_sudo_retry(
            self.host,
            arguments,
            execute_command,
        )

        if _success_exit_codes:
            status = return_code in _success_exit_codes
        else:
            status = return_code == 0

        return status, combined_output

    async def _async_run_command(
        self,
        command: str,
        stdin_value: Optional[str],
        get_pty: bool,
        timeout: Optional[int],
        print_output: bool,
        print_prefix: str,
    ) -> tuple[int, CommandOutput]:
        assert self._connection is not None, "SSH connection not initialised"

        try:
            result = await self._connection.run(
                command,
                check=False,
                term_type="xterm" if get_pty else None,
                input=stdin_value,
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            raise

        stdout = result.stdout or ""
        stderr = result.stderr or ""

        combined_lines: list[OutputLine] = []

        for line in stdout.splitlines():
            if print_output:
                click.echo(f"{print_prefix}{line}", err=True)
            combined_lines.append(OutputLine("stdout", line))

        for line in stderr.splitlines():
            if print_output:
                click.echo(f"{print_prefix}{click.style(line, 'red')}", err=True)
            combined_lines.append(OutputLine("stderr", line))

        return result.exit_status, CommandOutput(combined_lines)

    # File transfer helpers

    async def _ensure_sftp(self) -> asyncssh.SFTPClient:
        assert self._connection is not None, "SSH connection not initialised"
        if self._sftp_client is None:
            self._sftp_client = await self._connection.start_sftp_client()
        return self._sftp_client

    async def _async_read_file(self, remote_filename: str) -> bytes:
        sftp = await self._ensure_sftp()
        async with sftp.open(remote_filename, "rb") as remote_file:
            return await remote_file.read()

    async def _async_write_file(self, remote_filename: str, data: bytes) -> None:
        sftp = await self._ensure_sftp()
        async with sftp.open(remote_filename, "wb") as remote_file:
            await remote_file.write(data)

    async def _async_scp_upload(self, remote_filename: str, data: bytes) -> None:
        assert self._connection is not None, "SSH connection not initialised"

        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file.write(data)
            temp_file.flush()
            temp_path = temp_file.name

        try:
            await asyncssh.scp(temp_path, (self._connection, remote_filename))
        finally:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass

    async def _async_scp_download(self, remote_filename: str) -> bytes:
        assert self._connection is not None, "SSH connection not initialised"

        basename = os.path.basename(remote_filename.rstrip("/")) or "pyinfra-download"
        with tempfile.TemporaryDirectory() as temp_dir:
            local_path = os.path.join(temp_dir, basename)
            await asyncssh.scp((self._connection, remote_filename), local_path)
            with open(local_path, "rb") as local_file:
                return local_file.read()

    @memoize
    def get_file_transfer_connection(self) -> FileTransferClient:
        if self._transfer_protocol == "scp":
            return _SCPWrapper(self)
        return _SFTPWrapper(self)

    def _get_file(self, remote_filename: str, filename_or_io: str | IO) -> None:
        if self._transfer_protocol == "scp":
            data = self._submit(self._async_scp_download(remote_filename))
        else:
            data = self._submit(self._async_read_file(remote_filename))
        with get_file_io(filename_or_io, "wb") as file_io:
            file_io.write(data)

    def get_file(
        self,
        remote_filename: str,
        filename_or_io,
        remote_temp_filename=None,
        print_output: bool = False,
        print_input: bool = False,
        **arguments: Unpack["ConnectorArguments"],
    ) -> bool:
        _sudo = arguments.get("_sudo", False)
        _su_user = arguments.get("_su_user", None)

        if _sudo or _su_user:
            temp_file = remote_temp_filename or self.host.get_temp_filename(remote_filename)
            command = StringCommand("cp", remote_filename, temp_file, "&&", "chmod", "+r", temp_file)

            copy_status, output = self.run_shell_command(
                command,
                print_output=print_output,
                print_input=print_input,
                **arguments,
            )

            if copy_status is False:
                logger.error("File download copy temp error: %s", output.stderr)
                return False

            try:
                self._get_file(temp_file, filename_or_io)
            finally:
                self.run_shell_command(
                    StringCommand("rm", "-f", temp_file),
                    print_output=print_output,
                    print_input=print_input,
                    **arguments,
                )
        else:
            self._get_file(remote_filename, filename_or_io)

        if print_output:
            click.echo(f"{self.host.print_prefix}file downloaded: {remote_filename}", err=True)

        return True

    def _put_file(self, filename_or_io, remote_location):
        with get_file_io(filename_or_io) as file_io:
            data = file_io.read()
            if isinstance(data, str):
                data = data.encode()
            if self._transfer_protocol == "scp":
                self._submit(self._async_scp_upload(remote_location, data))
            else:
                self._submit(self._async_write_file(remote_location, data))

    def put_file(
        self,
        filename_or_io,
        remote_filename,
        remote_temp_filename=None,
        print_output: bool = False,
        print_input: bool = False,
        **arguments: Unpack["ConnectorArguments"],
    ) -> bool:
        original_arguments = arguments.copy()

        _sudo = arguments.pop("_sudo", False)
        _sudo_user = arguments.pop("_sudo_user", False)
        _doas = arguments.pop("_doas", False)
        _doas_user = arguments.pop("_doas_user", False)
        _su_user = arguments.pop("_su_user", None)

        if _sudo or _doas or _su_user:
            temp_file = remote_temp_filename or self.host.get_temp_filename(remote_filename)
            self._put_file(filename_or_io, temp_file)

            other_user = _su_user or _sudo_user or _doas_user
            if other_user:
                status, output = self.run_shell_command(
                    StringCommand("setfacl", "-m", f"u:{other_user}:r", temp_file),
                    print_output=print_output,
                    print_input=print_input,
                    **original_arguments,
                )
                if status is False:
                    logger.error("Unable to set ACL for temp file: %s", output.stderr)
                    return False

            command = StringCommand(
                "mv",
                temp_file,
                remote_filename,
                "&&",
                "chmod",
                "0644",
                remote_filename,
            )

            status, output = self.run_shell_command(
                command,
                print_output=print_output,
                print_input=print_input,
                **original_arguments,
            )

            if status is False:
                logger.error("File upload error: %s", output.stderr)
                return False

        else:
            self._put_file(filename_or_io, remote_filename)

        if print_output:
            click.echo(f"{self.host.print_prefix}file uploaded: {remote_filename}", err=True)

        return True

    # Rsync support remains shell-based

    def check_can_rsync(self) -> None:
        if self.data["ssh_key_password"]:
            raise NotImplementedError("Rsync does not currently work with SSH keys needing passwords.")

        if self.data["ssh_password"]:
            raise NotImplementedError("Rsync does not currently work with SSH passwords.")

        from shutil import which

        if not which("rsync"):
            raise NotImplementedError("The `rsync` binary is not available on this system.")

    def rsync(
        self,
        src: str,
        dest: str,
        flags: Iterable[str],
        print_output: bool = False,
        print_input: bool = False,
        **arguments: Unpack["ConnectorArguments"],
    ) -> bool:
        _sudo = arguments.pop("_sudo", False)
        _sudo_user = arguments.pop("_sudo_user", False)

        hostname = self.data["ssh_hostname"] or self.host.name
        user = self.data["ssh_user"]
        user_prefix = f"{user}@" if user else ""

        ssh_flags = ["-o BatchMode=yes"]

        if self._known_hosts_file:
            ssh_flags.append(f'-o "UserKnownHostsFile={shlex.quote(self._known_hosts_file)}"')

        strict_setting = (self._strict_host_key_checking or "accept-new").lower()
        ssh_flags.append(f'-o "StrictHostKeyChecking={shlex.quote(strict_setting)}"')

        ssh_config_file = self.data["ssh_config_file"]
        if ssh_config_file:
            ssh_flags.append(f"-F {shlex.quote(ssh_config_file)}")

        port = self.data["ssh_port"]
        if port:
            ssh_flags.append(f"-p {port}")

        ssh_key = self.data["ssh_key"]
        if ssh_key:
            ssh_flags.append(f"-i {shlex.quote(ssh_key)}")

        remote_rsync_command = "rsync"
        if _sudo:
            remote_rsync_command = "sudo rsync"
            if _sudo_user:
                remote_rsync_command = f"sudo -u {_sudo_user} rsync"

        rsync_command = (
            "rsync {rsync_flags} --rsh \"ssh {ssh_flags}\" --rsync-path '{remote_rsync_command}' "
            "{src} {user_prefix}{hostname}:{dest}"
        ).format(
            rsync_flags=" ".join(flags),
            ssh_flags=" ".join(ssh_flags),
            remote_rsync_command=remote_rsync_command,
            src=src,
            user_prefix=user_prefix,
            hostname=hostname,
            dest=dest,
        )

        if print_input:
            click.echo(f"{self.host.print_prefix}>>> {rsync_command}", err=True)

        return_code, output = run_local_process(
            rsync_command,
            print_output=print_output,
            print_prefix=self.host.print_prefix,
        )

        if return_code != 0:
            raise IOError(output.stderr)

        return True

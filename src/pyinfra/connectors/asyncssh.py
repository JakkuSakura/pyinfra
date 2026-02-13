from __future__ import annotations

from typing_extensions import override

from .ssh import SSHConnector


class AsyncSSHConnector(SSHConnector):
    handles_execution = True

    @override
    @staticmethod
    def make_names_data(name):
        yield f"@asyncssh/{name}", {"ssh_hostname": name}, []

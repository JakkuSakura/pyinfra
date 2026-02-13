from __future__ import annotations

from typing_extensions import override

from .ssh import SSHConnector


class SSHCLIConnector(SSHConnector):
    handles_execution = True

    @override
    @staticmethod
    def make_names_data(name):
        yield f"@ssh-cli/{name}", {"ssh_hostname": name}, []

    def __init__(self, state, host):
        super().__init__(state, host)
        self._use_ssh_cli = True

"""Run Helm release and repository operations."""

from __future__ import annotations

from pyinfra.api import StringCommand, operation


def _base_args(kubeconfig: str | None = None, namespace: str | None = None) -> list[str]:
    args = ["helm"]
    if kubeconfig:
        args.extend(["--kubeconfig", kubeconfig])
    if namespace:
        args.extend(["--namespace", namespace])
    return args


@operation(is_idempotent=False)
def repo(name: str, url: str, kubeconfig: str | None = None, force_update: bool = False):
    args = _base_args(kubeconfig=kubeconfig)
    args.extend(["repo", "add", name, url])
    if force_update:
        args.append("--force-update")
    yield StringCommand(*args)


@operation(is_idempotent=False)
def repo_update(kubeconfig: str | None = None):
    args = _base_args(kubeconfig=kubeconfig)
    args.extend(["repo", "update"])
    yield StringCommand(*args)


@operation(is_idempotent=False)
def upgrade_release(
    release: str,
    chart: str,
    namespace: str | None = None,
    kubeconfig: str | None = None,
    version: str | None = None,
    create_namespace: bool = True,
    wait: bool = True,
    timeout: str | None = None,
    set_values: dict[str, str | int | bool] | None = None,
):
    args = _base_args(kubeconfig=kubeconfig)
    args.extend(["upgrade", "--install", release, chart])

    if namespace:
        args.extend(["--namespace", namespace])
        if create_namespace:
            args.append("--create-namespace")

    if version:
        args.extend(["--version", version])

    if wait:
        args.append("--wait")

    if timeout:
        args.extend(["--timeout", timeout])

    if set_values:
        for key, value in set_values.items():
            args.extend(["--set", f"{key}={value}"])

    yield StringCommand(*args)

# Context helpers

The context helpers provide lightweight wrappers around the "big" deploy
machinery so you can run operations, deploys, or facts on demand. They reuse an
existing `State`, so your inventory and config continue to apply without
starting the full CLI.

## AsyncContext & AsyncHostContext

`pyinfra.async_context.AsyncContext` is an async context manager that connects to
the selected hosts when entered and disconnects them on exit. While inside the
context you can await operations and deploys directly, and fetch facts via the
host objects using `await host.get_fact(...)`.

```python
import asyncio

from pyinfra.api import Config, State, deploy
from pyinfra.async_context import AsyncContext, AsyncHostContext
from pyinfra.context import host
from pyinfra.facts.server import Hostname
from pyinfra.operations import server


async def run_all_hosts():
    inventory = ...  # construct your Inventory
    state = State(inventory, Config())

    @deploy("Example async deploy")
    def my_deploy():
        server.shell(name="Async deploy op", commands="echo async deploy")

    async with AsyncContext(state):
        await server.shell("echo hello from async")
        hostnames = {
            host: await host.get_fact(Hostname)
            for host in state.inventory
        }
        print(f"Hostnames: {hostnames}")

        await my_deploy()


async def run_single_host(state, host_name):
    @deploy("Per-host deploy")
    def my_host_deploy():
        server.shell(name="Host deploy op", commands="echo host deploy")

    async with AsyncHostContext(state, host_name):
        assert host is not None
        await server.shell("echo from single host")
        hostname = await host.get_fact(Hostname)
        print(hostname)

        await my_host_deploy()


asyncio.run(run_all_hosts())
```

`AsyncHostContext` scopes the helper to a single host (specified by name or by a
`Host` instance) but otherwise behaves the same. Both helpers accept a
`hosts=` override when you need to target a subset of hosts for a specific call.

## SyncContext & SyncHostContext

For synchronous code, `pyinfra.sync_context.SyncContext` and
`pyinfra.sync_context.SyncHostContext` mirror the async API without any asyncio
wrapping. The synchronous helpers still manage host connections for you and make
host facts available via `host.get_fact(...)`.

```python
from pyinfra.api import Config, State, deploy
from pyinfra.facts.server import Hostname
from pyinfra.context import host
from pyinfra.operations import server
from pyinfra.sync_context import SyncContext, SyncHostContext


def run_all_hosts():
    inventory = ...
    state = State(inventory, Config())

    @deploy("Example sync deploy")
    def my_sync_deploy():
        server.shell(name="Sync deploy op", commands="echo sync deploy")

    with SyncContext(state):
        server.shell("echo hello from sync")
        hostnames = {
            host: host.get_fact(Hostname)
            for host in state.inventory
        }
        print(f"Hostnames: {hostnames}")

        my_sync_deploy()


def run_single_host(state, host_name):
    @deploy("Sync per-host deploy")
    def my_sync_host_deploy():
        server.shell(name="Sync host deploy op", commands="echo sync host deploy")

    with SyncHostContext(state, host_name):
        assert host is not None
        server.shell("echo from sync single host")
        hostname = host.get_fact(Hostname)
        print(hostname)

        my_sync_host_deploy()
```

`SyncHostContext` accepts either the host name or the `Host` object directly and
ensures only that host is connected for the duration of the context. The sync
and async helpers can be mixed within the same project—choose the one that fits
the surrounding code.

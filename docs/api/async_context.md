# AsyncContext helper

`pyinfra.async_context.AsyncContext` gives you a small async-friendly wrapper to
run individual operations and facts without executing a full deploy. It reuses
the existing `State` object, so the same inventory/config settings apply.

```python
import asyncio

from pyinfra.api import Config, State, deploy
from pyinfra.async_context import AsyncContext, AsyncHostContext
from pyinfra.facts.server import Hostname
from pyinfra.operations import server


async def main() -> None:
    inventory = ...  # construct your Inventory
    state = State(inventory, Config())

    @deploy("Example async deploy")
    def my_deploy():
        server.shell(name="Async deploy op", commands="echo async deploy")

    async with AsyncContext(state) as ctx:
        await server.shell("echo hello from async")
        facts = {}
        for host in state.inventory:
            facts[host] = await host.get_fact(Hostname)
        print(f"Hostnames: {facts}")

        await my_deploy()


asyncio.run(main())
```

`AsyncContext` is an async context manager and will automatically connect to the
target hosts on entry and disconnect them when the block exits. While inside the
context you can call operations or deploys directly (for example
`await server.shell(...)` or `await my_deploy()`). Facts are retrieved via the
host objects themselves—`await host.get_fact(...)`—which makes the syntax mirror
the synchronous helper. If you only want to target a subset of hosts you can
pass them via the `hosts=` parameter when creating the context or when calling
individual operations/deploys using the normal global arguments.

### Working with a single host

When you only need to operate on one host you can use
`pyinfra.async_context.AsyncHostContext`, which is just a thin wrapper that
builds an `AsyncContext` scoped to a single host:

```python
from pyinfra.async_context import AsyncHostContext
from pyinfra.facts.server import Hostname
from pyinfra.operations import server


async def run_against_host(state, host):
    @deploy("Per-host deploy")
    def my_host_deploy():
        server.shell(name="Host deploy op", commands="echo host deploy")

    async with AsyncHostContext(state, host) as ctx:
        await server.shell("echo from single host")
        hostname = await host.get_fact(Hostname)
        print(hostname)

        await my_host_deploy()
```

`AsyncHostContext` accepts either the host name (string) or a `Host` object from
the state inventory. The sync equivalent is available as
`pyinfra.sync_context.SyncHostContext` and behaves the same way.

## Synchronous helper

For synchronous code you can use `pyinfra.sync_context.SyncContext`, which
exposes the same API without the asyncio wrappers:

```python
from pyinfra.api import Config, State, deploy
from pyinfra.facts.server import Hostname
from pyinfra.operations import server
from pyinfra.sync_context import SyncContext


def main() -> None:
    inventory = ...
    state = State(inventory, Config())

    @deploy("Example sync deploy")
    def my_sync_deploy():
        server.shell(name="Sync deploy op", commands="echo sync deploy")

    with SyncContext(state) as ctx:
        server.shell("echo hello from sync")
        facts = {host: host.get_fact(Hostname) for host in state.inventory}
        print(f"Hostnames: {facts}")

        my_sync_deploy()


main()
```

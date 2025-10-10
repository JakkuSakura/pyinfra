# AsyncContext helper

`pyinfra.async_context.AsyncContext` gives you a small async-friendly wrapper to
run individual operations and facts without executing a full deploy. It reuses
the existing `State` object, so the same inventory/config settings apply.

```python
import asyncio

from pyinfra.api import Config, State
from pyinfra.async_context import AsyncContext
from pyinfra.facts.server import Hostname
from pyinfra.operations import server


async def main() -> None:
    inventory = ...  # construct your Inventory
    state = State(inventory, Config())

    async with AsyncContext(state) as ctx:
        await server.shell("echo hello from async")
        facts = await ctx.get_fact(Hostname)
        print(f"Hostnames: {facts}")


asyncio.run(main())
```

`AsyncContext` is an async context manager and will automatically connect to the
target hosts on entry and disconnect them when the block exits. While inside the
context you can call operations directly (for example `await server.shell(...)`);
the operation will execute immediately for the selected hosts and return a
mapping of host to `OperationMeta`. If you only want to target a subset of hosts
you can pass them via the `hosts=` parameter when creating the context or when
calling `server.shell(..., hosts=[...])`/`ctx.get_fact(..., hosts=[...])`.

## Synchronous helper

For synchronous code you can use `pyinfra.sync_context.SyncContext`, which
exposes the same API without the asyncio wrappers:

```python
from pyinfra.api import Config, State
from pyinfra.facts.server import Hostname
from pyinfra.operations import server
from pyinfra.sync_context import SyncContext


def main() -> None:
    inventory = ...
    state = State(inventory, Config())

    with SyncContext(state) as ctx:
        server.shell("echo hello from sync")
        facts = ctx.get_fact(Hostname)
        print(f"Hostnames: {facts}")


main()
```

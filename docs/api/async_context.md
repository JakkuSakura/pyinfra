# AsyncContext helper

`pyinfra.async_context.AsyncContext` gives you a small async-friendly wrapper to
run individual operations and facts without executing a full deploy. It reuses
the existing `State` object, so the same inventory/config settings apply.

```python
import asyncio

from pyinfra.api import Config, State
from pyinfra.api.connect import connect_all_async, disconnect_all_async
from pyinfra.async_context import AsyncContext
from pyinfra.facts.server import Hostname
from pyinfra.operations import server


async def main() -> None:
    inventory = ...  # construct your Inventory
    state = State(inventory, Config())

    await connect_all_async(state)

    ctx = AsyncContext(state)
    await ctx.run_operation(server.shell, "echo hello from async")
    facts = await ctx.get_fact(Hostname)
    print(f"Hostnames: {facts}")

    await disconnect_all_async(state)


asyncio.run(main())
```

If you only want to target a subset of hosts you can pass them via the
`hosts=` parameter when creating the context or when calling
`run_operation`/`get_fact`.

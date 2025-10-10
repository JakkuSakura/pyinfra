from __future__ import annotations

from contextlib import ExitStack
from functools import partial
from typing import Any, Iterable, Mapping

from typing_extensions import Protocol

from pyinfra.api.host import Host
from pyinfra.api.operation import OperationMeta, execute_immediately
from pyinfra.api.state import State, StateStage
from pyinfra.context import ctx_config, ctx_host, ctx_inventory, ctx_state


class SupportsOperation(Protocol):
    def __call__(self, *args, **kwargs) -> OperationMeta:  # pragma: no cover - Protocol stub
        ...


class AsyncContext:
    """Async helper for running individual operations or facts against hosts."""

    def __init__(
        self,
        state: State,
        hosts: Iterable[Host | str] | None = None,
    ) -> None:
        self.state = state
        self._default_hosts = self._normalise_hosts(hosts)

    def _normalise_hosts(self, hosts: Iterable[Host | str] | None) -> list[Host]:
        if hosts is None:
            return list(self.state.inventory.iter_active_hosts()) or list(self.state.inventory)

        normalised: list[Host] = []
        for host in hosts:
            if isinstance(host, Host):
                normalised.append(host)
            else:
                resolved = self.state.inventory.get_host(host)
                if resolved is None:
                    raise ValueError(f"Unknown host: {host}")
                normalised.append(resolved)
        return normalised

    def _with_context(self, host: Host):
        stack = ExitStack()
        stack.enter_context(ctx_state.use(self.state))
        stack.enter_context(ctx_inventory.use(self.state.inventory))
        stack.enter_context(ctx_config.use(self.state.config.copy()))
        stack.enter_context(ctx_host.use(host))
        return stack

    async def run_operation(
        self,
        operation: SupportsOperation,
        *args,
        hosts: Iterable[Host | str] | None = None,
        **kwargs,
    ) -> Mapping[Host, OperationMeta]:
        """Execute an operation immediately for each host and await completion."""

        targets = self._normalise_hosts(hosts) if hosts is not None else self._default_hosts

        results = {}
        for host in targets:
            op_meta = await self.state.run_in_executor(
                partial(self._execute_operation, host, operation, args, kwargs)
            )
            results[host] = op_meta
        return results

    def _execute_operation(
        self,
        host: Host,
        operation: SupportsOperation,
        op_args: tuple[Any, ...],
        op_kwargs: dict[str, Any],
    ) -> OperationMeta:
        with self._with_context(host):
            if self.state.current_stage < StateStage.Prepare:
                self.state.set_stage(StateStage.Prepare)
            if self.state.current_stage < StateStage.Execute:
                self.state.set_stage(StateStage.Execute)

            was_executing = self.state.is_executing
            if not was_executing:
                self.state.is_executing = True

            if host not in self.state.activated_hosts:
                self.state.activate_host(host)

            try:
                op_meta = operation(*op_args, **op_kwargs)

                if not op_meta.is_complete():
                    execute_immediately(self.state, host, op_meta._hash)

                return op_meta
            finally:
                if not was_executing:
                    self.state.is_executing = False

    async def get_fact(
        self,
        fact_cls,
        *fact_args,
        hosts: Iterable[Host | str] | None = None,
        **fact_kwargs,
    ) -> Mapping[Host, Any]:
        """Fetch a fact asynchronously for the selected hosts."""

        targets = self._normalise_hosts(hosts) if hosts is not None else self._default_hosts

        results = {}
        for host in targets:
            value = await self.state.run_in_executor(
                partial(self._fetch_fact, host, fact_cls, fact_args, fact_kwargs)
            )
            results[host] = value
        return results

    def _fetch_fact(
        self,
        host: Host,
        fact_cls,
        fact_args: tuple[Any, ...],
        fact_kwargs: dict[str, Any],
    ) -> Any:
        with self._with_context(host):
            return host.get_fact(fact_cls, *fact_args, **fact_kwargs)

from __future__ import annotations

import pytest

from k8s_troubleshooter.config import AppConfig
from k8s_troubleshooter.harness.executor import ToolExecutor
from k8s_troubleshooter.harness.policy import PolicyContext, PolicyGuard
from k8s_troubleshooter.harness.schema import ToolCall, ToolSpec
from k8s_troubleshooter.harness.tools import ToolRegistry
from k8s_troubleshooter.harness.trace import TraceLogger


def _make_registry() -> tuple[ToolRegistry, ToolExecutor]:
    registry = ToolRegistry()
    config = AppConfig()

    async def mock_handler(namespace: str, **kwargs) -> dict:
        return {"namespace": namespace, "status": "ok"}

    registry.register(
        ToolSpec(name="get_pod", description="Get Pod", readonly=True, timeout_seconds=5),
        mock_handler,
    )
    trace = TraceLogger()
    guard = PolicyGuard(config)
    executor = ToolExecutor(registry, guard, trace)
    return registry, executor


class TestToolExecutor:
    async def test_execute_success(self):
        _, executor = _make_registry()
        call = ToolCall(name="get_pod", arguments={"namespace": "default"})
        ctx = PolicyContext()
        result = await executor.execute(call, ctx)
        assert result.status == "success"
        assert result.data["namespace"] == "default"

    async def test_execute_unknown_tool(self):
        _, executor = _make_registry()
        call = ToolCall(name="nonexistent", arguments={})
        ctx = PolicyContext()
        result = await executor.execute(call, ctx)
        assert result.status == "error"
        assert "Unknown tool" in result.error

    async def test_execute_denied_by_policy(self):
        registry = ToolRegistry()
        config = AppConfig(max_tool_calls=0)
        trace = TraceLogger()
        guard = PolicyGuard(config)

        async def handler(**kwargs):
            return {}

        registry.register(ToolSpec(name="get_pod", description="", readonly=True), handler)
        executor = ToolExecutor(registry, guard, trace)

        call = ToolCall(name="get_pod", arguments={"namespace": "default"})
        ctx = PolicyContext(tool_call_count=0)
        result = await executor.execute(call, ctx)
        assert result.status == "denied"

    async def test_execute_plan(self):
        _, executor = _make_registry()
        calls = [
            ToolCall(name="get_pod", arguments={"namespace": "default"}),
            ToolCall(name="get_pod", arguments={"namespace": "kube-system"}),
        ]
        ctx = PolicyContext()
        results = await executor.execute_plan(calls, ctx)
        assert len(results) == 2
        assert all(r.status == "success" for r in results)
        assert ctx.tool_call_count == 2

    async def test_execute_timeout(self):
        registry = ToolRegistry()
        config = AppConfig()
        trace = TraceLogger()
        guard = PolicyGuard(config)

        import asyncio

        async def slow_handler(**kwargs):
            await asyncio.sleep(10)
            return {}

        registry.register(
            ToolSpec(name="slow_tool", description="", readonly=True, timeout_seconds=1),
            slow_handler,
        )
        executor = ToolExecutor(registry, guard, trace)

        call = ToolCall(name="slow_tool", arguments={})
        ctx = PolicyContext()
        result = await executor.execute(call, ctx)
        assert result.status == "error"
        assert "Timeout" in result.error

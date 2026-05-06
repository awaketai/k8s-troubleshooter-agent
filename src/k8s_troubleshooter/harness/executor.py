from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

from k8s_troubleshooter.harness.policy import PolicyContext, PolicyGuard
from k8s_troubleshooter.harness.schema import ToolCall, ToolResult
from k8s_troubleshooter.harness.tools import ToolRegistry
from k8s_troubleshooter.harness.trace import TraceLogger


class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        policy_guard: PolicyGuard,
        trace_logger: TraceLogger,
    ) -> None:
        self._registry = registry
        self._policy_guard = policy_guard
        self._trace = trace_logger

    async def execute(
        self, tool_call: ToolCall, policy_context: PolicyContext
    ) -> ToolResult:
        entry = self._registry.get(tool_call.name)
        if entry is None:
            return ToolResult(
                name=tool_call.name,
                status="error",
                error=f"Unknown tool: {tool_call.name}",
                duration_ms=0,
            )

        spec, handler = entry

        decision = self._policy_guard.check_tool_call(tool_call, spec, policy_context)
        if not decision.allowed:
            self._trace.log_policy_decision(
                tool_name=tool_call.name, allowed=False, reason=decision.reason
            )
            return ToolResult(
                name=tool_call.name, status="denied", error=decision.reason, duration_ms=0
            )

        start = time.monotonic()
        try:
            result = await asyncio.wait_for(
                self._call_handler(handler, tool_call.arguments),
                timeout=spec.timeout_seconds,
            )
            duration_ms = int((time.monotonic() - start) * 1000)

            if spec.redaction_policy and isinstance(result, dict):
                result = self._redact(result, spec.redaction_policy)

            if tool_call.name == "check_secret_exists" and isinstance(result, dict):
                result = {k: v for k, v in result.items() if k in ("exists", "type", "keys")}

            self._trace.log_tool_call(
                tool_name=tool_call.name,
                arguments=tool_call.arguments,
                status="success",
                duration_ms=duration_ms,
                result_summary=self._summary(result),
            )

            return ToolResult(
                name=tool_call.name, status="success", data=result, duration_ms=duration_ms
            )

        except asyncio.TimeoutError:
            duration_ms = int((time.monotonic() - start) * 1000)
            self._trace.log_tool_call(
                tool_name=tool_call.name,
                arguments=tool_call.arguments,
                status="error",
                duration_ms=duration_ms,
                result_summary=None,
            )
            return ToolResult(
                name=tool_call.name,
                status="error",
                error=f"Timeout after {spec.timeout_seconds}s",
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = int((time.monotonic() - start) * 1000)
            self._trace.log_tool_call(
                tool_name=tool_call.name,
                arguments=tool_call.arguments,
                status="error",
                duration_ms=duration_ms,
                result_summary=None,
            )
            return ToolResult(
                name=tool_call.name, status="error", error=str(e), duration_ms=duration_ms
            )

    async def execute_plan(
        self, tool_calls: list[ToolCall], policy_context: PolicyContext
    ) -> list[ToolResult]:
        results: list[ToolResult] = []
        for call in tool_calls:
            policy_context.tool_call_count += 1
            result = await self.execute(call, policy_context)
            results.append(result)
        return results

    @staticmethod
    async def _call_handler(handler: Callable, arguments: dict) -> Any:
        result = handler(**arguments)
        if asyncio.iscoroutine(result):
            result = await result
        return result

    @staticmethod
    def _redact(data: dict, policy: str) -> dict:
        if policy == "remove_secret_values":
            return {k: "[REDACTED]" for k in data}
        return data

    @staticmethod
    def _summary(result: Any) -> dict | None:
        if isinstance(result, dict):
            return {k: type(v).__name__ for k, v in result.items()}
        return None

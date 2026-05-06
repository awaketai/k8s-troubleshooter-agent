from __future__ import annotations

import re
from dataclasses import dataclass, field

from k8s_troubleshooter.config import AppConfig
from k8s_troubleshooter.harness.schema import ToolCall, ToolSpec


@dataclass
class PolicyContext:
    tool_call_count: int = 0
    namespace: str | None = None


@dataclass
class PolicyDecision:
    allowed: bool
    reason: str = ""


class PolicyGuard:
    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def check_tool_call(
        self, tool_call: ToolCall, tool_spec: ToolSpec, context: PolicyContext
    ) -> PolicyDecision:
        if not tool_spec.readonly:
            return PolicyDecision(allowed=False, reason="Write operations are not allowed")

        if context.tool_call_count >= self._config.max_tool_calls:
            return PolicyDecision(
                allowed=False,
                reason=f"Tool call limit ({self._config.max_tool_calls}) exceeded",
            )

        if tool_call.name == "check_secret_exists" and not self._config.enable_secret_check:
            return PolicyDecision(
                allowed=False,
                reason="Secret check is not enabled. Use --enable-secret-check to enable.",
            )

        allowed_ns = self._config.allowed_namespaces
        if allowed_ns:
            # Check both context namespace and tool call argument namespace
            namespaces_to_check = set()
            if context.namespace:
                namespaces_to_check.add(context.namespace)
            tool_ns = tool_call.arguments.get("namespace")
            if tool_ns:
                namespaces_to_check.add(tool_ns)
            for ns in namespaces_to_check:
                if ns not in allowed_ns:
                    return PolicyDecision(
                        allowed=False,
                        reason=f"Namespace '{ns}' is not in the allowed list",
                    )

        return PolicyDecision(allowed=True)

    def check_llm_input(self, content: str) -> str:
        redacted = content
        sensitive_patterns = [
            r"-----BEGIN\s+\w+[^-]*-----[\s\S]*?-----END\s+\w+[^-]*-----",
            r"-----BEGIN\s+\w+[^-]*-----",
            r"(?i)token[:\s]+[\w\-._~+/=]+",
            r"(?i)password[:\s]+[\w\-._~+/=]+",
            r"(?i)secret[:\s]+[\w\-._~+/=]+",
            r"Bearer\s+[\w\-._~:/?#\[\]@!$&'()*+,;%=]+",
        ]
        for pattern in sensitive_patterns:
            redacted = re.sub(pattern, "[REDACTED]", redacted, flags=re.IGNORECASE)

        max_size = 100_000
        if len(redacted) > max_size:
            redacted = redacted[:max_size] + "\n... [truncated] ..."

        return redacted

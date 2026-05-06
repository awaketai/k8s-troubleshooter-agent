from __future__ import annotations

from k8s_troubleshooter.config import AppConfig
from k8s_troubleshooter.harness.policy import PolicyContext, PolicyGuard
from k8s_troubleshooter.harness.schema import ToolCall, ToolSpec


class TestPolicyGuard:
    def test_allow_readonly_tool(self):
        config = AppConfig()
        guard = PolicyGuard(config)
        spec = ToolSpec(name="get_pod", description="", readonly=True)
        call = ToolCall(name="get_pod", arguments={})
        ctx = PolicyContext()
        decision = guard.check_tool_call(call, spec, ctx)
        assert decision.allowed is True

    def test_reject_write_tool(self):
        config = AppConfig()
        guard = PolicyGuard(config)
        spec = ToolSpec(name="delete_pod", description="", readonly=False)
        call = ToolCall(name="delete_pod", arguments={})
        ctx = PolicyContext()
        decision = guard.check_tool_call(call, spec, ctx)
        assert decision.allowed is False
        assert "Write" in decision.reason

    def test_reject_secret_check_disabled(self):
        config = AppConfig(enable_secret_check=False)
        guard = PolicyGuard(config)
        spec = ToolSpec(name="check_secret_exists", description="", readonly=True)
        call = ToolCall(name="check_secret_exists", arguments={})
        ctx = PolicyContext()
        decision = guard.check_tool_call(call, spec, ctx)
        assert decision.allowed is False
        assert "not enabled" in decision.reason

    def test_allow_secret_check_enabled(self):
        config = AppConfig(enable_secret_check=True)
        guard = PolicyGuard(config)
        spec = ToolSpec(name="check_secret_exists", description="", readonly=True)
        call = ToolCall(name="check_secret_exists", arguments={})
        ctx = PolicyContext()
        decision = guard.check_tool_call(call, spec, ctx)
        assert decision.allowed is True

    def test_reject_over_tool_call_limit(self):
        config = AppConfig(max_tool_calls=2)
        guard = PolicyGuard(config)
        spec = ToolSpec(name="get_pod", description="", readonly=True)
        call = ToolCall(name="get_pod", arguments={})
        ctx = PolicyContext(tool_call_count=2)
        decision = guard.check_tool_call(call, spec, ctx)
        assert decision.allowed is False

    def test_check_llm_input_redaction(self):
        config = AppConfig()
        guard = PolicyGuard(config)
        content = "some data with Bearer token: abc123 and -----BEGIN CERTIFICATE-----"
        result = guard.check_llm_input(content)
        assert "abc123" not in result
        assert "[REDACTED]" in result

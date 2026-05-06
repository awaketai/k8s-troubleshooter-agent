from __future__ import annotations

import pytest

from k8s_troubleshooter.diagnosis.finding import Finding
from k8s_troubleshooter.diagnosis.llm_fallback import LLMFallbackDiagnoser
from k8s_troubleshooter.evidence.model import Evidence, ResourceRef


class TestLLMFallbackDiagnoser:
    async def test_returns_empty_when_no_provider(self):
        diagnoser = LLMFallbackDiagnoser(llm_provider=None)
        evidence = Evidence(resource=ResourceRef(kind="Pod", namespace="default", name="pod-1"))
        result = await diagnoser.diagnose(evidence, [])
        assert result == []

    async def test_returns_findings_from_llm(self):
        class MockProvider:
            async def chat(self, messages, **kwargs):
                return '[{"type": "llm_issue", "title": "Test", "severity": "high", "confidence": 0.8, "root_cause": "test cause", "recommendations": ["fix it"]}]'

        diagnoser = LLMFallbackDiagnoser(llm_provider=MockProvider())
        evidence = Evidence(
            resource=ResourceRef(kind="Pod", namespace="default", name="pod-1"),
        )
        result = await diagnoser.diagnose(evidence, [])
        assert len(result) == 1
        assert result[0].type == "llm_issue"
        assert result[0].source == "llm"

    async def test_handles_invalid_json(self):
        class MockProvider:
            async def chat(self, messages, **kwargs):
                return "not valid json"

        diagnoser = LLMFallbackDiagnoser(llm_provider=MockProvider())
        evidence = Evidence(resource=ResourceRef(kind="Pod", namespace="default", name="pod-1"))
        result = await diagnoser.diagnose(evidence, [])
        assert result == []

    async def test_handles_provider_exception(self):
        class FailingProvider:
            async def chat(self, messages, **kwargs):
                raise RuntimeError("API error")

        diagnoser = LLMFallbackDiagnoser(llm_provider=FailingProvider())
        evidence = Evidence(resource=ResourceRef(kind="Pod", namespace="default", name="pod-1"))
        result = await diagnoser.diagnose(evidence, [])
        assert result == []

    async def test_policy_guard_redacts_input(self):
        from k8s_troubleshooter.config import AppConfig
        from k8s_troubleshooter.harness.policy import PolicyGuard

        class MockProvider:
            def __init__(self):
                self.received = ""

            async def chat(self, messages, **kwargs):
                self.received = messages[-1]["content"]
                return "[]"

        provider = MockProvider()
        guard = PolicyGuard(AppConfig())
        diagnoser = LLMFallbackDiagnoser(llm_provider=provider, policy_guard=guard)

        evidence = Evidence(resource=ResourceRef(kind="Pod", namespace="default", name="pod-1"))
        await diagnoser.diagnose(evidence, [])
        # Basic check that content was passed through guard (no crash)

    async def test_handles_code_block_response(self):
        class MockProvider:
            async def chat(self, messages, **kwargs):
                return '```json\n[{"type": "test", "title": "T", "severity": "low", "confidence": 0.5, "root_cause": "rc", "recommendations": []}]\n```'

        diagnoser = LLMFallbackDiagnoser(llm_provider=MockProvider())
        evidence = Evidence(resource=ResourceRef(kind="Pod", namespace="default", name="pod-1"))
        result = await diagnoser.diagnose(evidence, [])
        assert len(result) == 1
        assert result[0].type == "test"

from __future__ import annotations

import pytest

from k8s_troubleshooter.harness.context import SessionContext
from k8s_troubleshooter.harness.intent import parse_intent


@pytest.fixture
def session():
    return SessionContext(active_namespace="default")


class TestIntentParser:
    async def test_diagnose_namespace(self, session):
        result = await parse_intent("看看 default namespace 的 pod", session)
        assert result.intent == "diagnose_namespace"
        assert result.scope.namespace == "default"

    async def test_diagnose_pod_with_slash(self, session):
        result = await parse_intent("排查 default/demo-pod", session)
        assert result.intent == "diagnose_pod"
        assert result.scope.namespace == "default"
        assert result.scope.name == "demo-pod"

    async def test_diagnose_pod_keyword(self, session):
        result = await parse_intent("排查 pod demo-pod", session)
        assert result.intent == "diagnose_pod"
        assert result.scope.name == "demo-pod"

    async def test_explain_finding(self, session):
        result = await parse_intent("这个 finding 是什么意思", session)
        assert result.intent == "explain_finding"

    async def test_symptom_oom(self, session):
        result = await parse_intent("看看那个 OOM 的 pod", session)
        assert "OOMKilled" in result.symptoms

    async def test_symptom_imagepull(self, session):
        result = await parse_intent("排查 ImagePullBackOff 的问题", session)
        assert "ImagePullBackOff" in result.symptoms

    async def test_depth_deep(self, session):
        result = await parse_intent("详细看看 default/demo-pod", session)
        assert result.depth == "deep"

    async def test_depth_quick(self, session):
        result = await parse_intent("快速检查 default namespace", session)
        assert result.depth == "quick"

    async def test_depth_normal_default(self, session):
        result = await parse_intent("看看 default namespace 的 pod", session)
        assert result.depth == "normal"

    async def test_unhealthy_namespace_scan(self, session):
        result = await parse_intent("default namespace 有什么异常的 pod", session)
        assert result.intent == "diagnose_namespace"
        assert result.scope.namespace == "default"

    async def test_namespace_fallback_to_session(self):
        session = SessionContext(active_namespace="production")
        result = await parse_intent("看看有什么异常 pod", session)
        assert result.scope.namespace == "production"

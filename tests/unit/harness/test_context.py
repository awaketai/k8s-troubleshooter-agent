from __future__ import annotations

import pytest

from k8s_troubleshooter.diagnosis.finding import Finding
from k8s_troubleshooter.evidence.model import ResourceRef
from k8s_troubleshooter.harness.context import SessionContext, resolve_context
from k8s_troubleshooter.harness.schema import DiagnosisRequest, DiagnosisResult, ResourceScope


class TestSessionContext:
    def test_update_appends_resource(self):
        ctx = SessionContext(active_namespace="default")
        result = DiagnosisResult(
            request=DiagnosisRequest(intent="diagnose_pod", scope=ResourceScope(kind="Pod", namespace="default", name="pod-1")),
            resource=ResourceRef(kind="Pod", namespace="default", name="pod-1"),
            findings=[Finding(type="test", title="Test", source="rule")],
        )
        ctx.update(result)
        assert len(ctx.last_diagnosed_resources) == 1
        assert ctx.last_diagnosed_resources[0].name == "pod-1"

    def test_update_truncates_resources_at_20(self):
        ctx = SessionContext(active_namespace="default")
        for i in range(25):
            result = DiagnosisResult(
                request=DiagnosisRequest(intent="diagnose_pod", scope=ResourceScope(kind="Pod", namespace="default", name=f"pod-{i}")),
                resource=ResourceRef(kind="Pod", namespace="default", name=f"pod-{i}"),
                findings=[],
            )
            ctx.update(result)
        assert len(ctx.last_diagnosed_resources) == 20
        assert ctx.last_diagnosed_resources[0].name == "pod-5"

    def test_update_sets_active_findings(self):
        ctx = SessionContext(active_namespace="default")
        findings = [Finding(type="test", title="Test", source="rule")]
        result = DiagnosisResult(
            request=DiagnosisRequest(intent="diagnose_pod", scope=ResourceScope(kind="Pod", namespace="default", name="pod-1")),
            resource=ResourceRef(kind="Pod", namespace="default", name="pod-1"),
            findings=findings,
        )
        ctx.update(result)
        assert ctx.active_findings == findings


class TestResolveContext:
    def test_fills_namespace_from_session(self):
        session = SessionContext(active_namespace="production")
        request = DiagnosisRequest(
            intent="diagnose_namespace",
            scope=ResourceScope(kind="Namespace"),
        )
        result = resolve_context(request, session)
        assert result.scope.namespace == "production"

    def test_does_not_override_explicit_namespace(self):
        session = SessionContext(active_namespace="production")
        request = DiagnosisRequest(
            intent="diagnose_namespace",
            scope=ResourceScope(kind="Namespace", namespace="staging"),
        )
        result = resolve_context(request, session)
        assert result.scope.namespace == "staging"

    def test_fills_symptoms_from_active_findings(self):
        session = SessionContext(active_namespace="default")
        session.active_findings = [Finding(type="OOMKilled", title="OOM", source="rule")]
        request = DiagnosisRequest(
            intent="diagnose_pod",
            scope=ResourceScope(kind="Pod", namespace="default", name="pod-1"),
            symptoms=[],
        )
        result = resolve_context(request, session)
        assert "OOMKilled" in result.symptoms

    def test_does_not_override_existing_symptoms(self):
        session = SessionContext(active_namespace="default")
        session.active_findings = [Finding(type="OOMKilled", title="OOM", source="rule")]
        request = DiagnosisRequest(
            intent="diagnose_pod",
            scope=ResourceScope(kind="Pod", namespace="default", name="pod-1"),
            symptoms=["CrashLoopBackOff"],
        )
        result = resolve_context(request, session)
        assert result.symptoms == ["CrashLoopBackOff"]

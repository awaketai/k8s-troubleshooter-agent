from __future__ import annotations

import pytest

from k8s_troubleshooter.diagnosis.engine import DiagnosisEngine
from k8s_troubleshooter.diagnosis.finding import Finding
from k8s_troubleshooter.diagnosis.llm_fallback import LLMFallbackDiagnoser
from k8s_troubleshooter.evidence.model import Evidence, ResourceRef
from k8s_troubleshooter.harness.schema import DiagnosisRequest, ResourceScope


@pytest.fixture
def healthy_evidence():
    return Evidence(
        resource=ResourceRef(kind="Pod", namespace="default", name="healthy-pod"),
        pod={"namespace": "default", "name": "healthy-pod", "phase": "Running",
             "container_statuses": [{"name": "main", "ready": True, "state": "running"}]},
    )


@pytest.fixture
def normal_request():
    return DiagnosisRequest(
        intent="diagnose_pod",
        scope=ResourceScope(kind="Pod", namespace="default", name="test-pod"),
    )


class TestDiagnosisEngine:
    def test_no_rule_findings_triggers_llm(self, healthy_evidence, normal_request):
        engine = DiagnosisEngine(diagnosers=[], llm_fallback=LLMFallbackDiagnoser())
        assert engine._should_use_llm(normal_request, healthy_evidence, []) is True

    def test_low_confidence_triggers_llm(self, healthy_evidence, normal_request):
        findings = [Finding(type="test", title="test", confidence=0.3, source="rule")]
        engine = DiagnosisEngine(diagnosers=[], llm_fallback=LLMFallbackDiagnoser())
        assert engine._should_use_llm(normal_request, healthy_evidence, findings) is True

    def test_needs_llm_analysis_triggers_llm(self, healthy_evidence, normal_request):
        findings = [Finding(type="test", title="test", confidence=0.9, source="rule", needs_llm_analysis=True)]
        engine = DiagnosisEngine(diagnosers=[], llm_fallback=LLMFallbackDiagnoser())
        assert engine._should_use_llm(normal_request, healthy_evidence, findings) is True

    def test_deep_depth_triggers_llm(self, healthy_evidence):
        request = DiagnosisRequest(
            intent="diagnose_pod",
            scope=ResourceScope(kind="Pod", namespace="default", name="test-pod"),
            depth="deep",
        )
        findings = [Finding(type="test", title="test", confidence=0.9, source="rule")]
        engine = DiagnosisEngine(diagnosers=[], llm_fallback=LLMFallbackDiagnoser())
        assert engine._should_use_llm(request, healthy_evidence, findings) is True

    def test_merge_findings_sorted_by_severity(self):
        findings = [
            Finding(type="a", title="A", severity="low", confidence=0.9, source="rule"),
            Finding(type="b", title="B", severity="high", confidence=0.8, source="rule"),
            Finding(type="c", title="C", severity="critical", confidence=0.7, source="llm"),
        ]
        merged = DiagnosisEngine._merge_findings(findings, [])
        assert merged[0].severity == "critical"
        assert merged[1].severity == "high"
        assert merged[2].severity == "low"

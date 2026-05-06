from __future__ import annotations

import pytest

from k8s_troubleshooter.harness.context import SessionContext
from k8s_troubleshooter.harness.schema import DiagnosisRequest, ResourceScope
from k8s_troubleshooter.harness.validator import validate_request


class TestValidator:
    def test_valid_diagnose_pod(self):
        req = DiagnosisRequest(
            intent="diagnose_pod",
            scope=ResourceScope(kind="Pod", namespace="default", name="demo-pod"),
        )
        result = validate_request(req)
        assert result.valid is True

    def test_valid_diagnose_namespace(self):
        req = DiagnosisRequest(
            intent="diagnose_namespace",
            scope=ResourceScope(kind="Namespace", namespace="default"),
        )
        result = validate_request(req)
        assert result.valid is True

    def test_missing_namespace_for_diagnose_pod(self):
        req = DiagnosisRequest(
            intent="diagnose_pod",
            scope=ResourceScope(kind="Pod", name="demo-pod"),
        )
        result = validate_request(req)
        assert result.valid is False

    def test_dry_run_rejected(self):
        req = DiagnosisRequest(
            intent="diagnose_pod",
            scope=ResourceScope(kind="Pod", namespace="default", name="demo-pod"),
            mode="dry_run",
        )
        result = validate_request(req)
        assert result.valid is False

    def test_diagnose_workload_unsupported(self):
        req = DiagnosisRequest(
            intent="diagnose_workload",
            scope=ResourceScope(kind="Deployment", namespace="default", name="my-deploy"),
        )
        result = validate_request(req)
        assert result.valid is False
        assert "不支持" in (result.clarification_question or "")

    def test_explain_finding_without_active_findings(self):
        req = DiagnosisRequest(
            intent="explain_finding",
            scope=ResourceScope(kind="Pod", namespace="default"),
        )
        session = SessionContext()
        result = validate_request(req, session)
        assert result.valid is False

    def test_apply_mode_rejected(self):
        req = DiagnosisRequest(
            intent="diagnose_pod",
            scope=ResourceScope(kind="Pod", namespace="default", name="demo-pod"),
            mode="apply",
        )
        result = validate_request(req)
        assert result.valid is False

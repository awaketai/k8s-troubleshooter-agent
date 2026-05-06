from __future__ import annotations

from typing import Any, Callable, Literal

from pydantic import BaseModel

from k8s_troubleshooter.diagnosis.finding import Finding
from k8s_troubleshooter.evidence.model import ResourceRef


class ResourceScope(BaseModel):
    kind: str
    namespace: str | None = None
    name: str | None = None


class DiagnosisRequest(BaseModel):
    intent: Literal[
        "diagnose_pod",
        "diagnose_namespace",
        "explain_finding",
        "diagnose_workload",
    ]
    scope: ResourceScope
    symptoms: list[str] = []
    filters: dict[str, Any] = {}
    mode: Literal["readonly", "dry_run", "apply"] = "readonly"
    depth: Literal["quick", "normal", "deep"] = "normal"
    needs_clarification: bool = False
    clarification_question: str | None = None


class DiagnosisResult(BaseModel):
    request: DiagnosisRequest
    resource: ResourceRef
    status: str | None = None
    findings: list[Finding] = []
    evidence_summary: dict[str, Any] = {}
    trace_id: str = ""


class ToolCall(BaseModel):
    name: str
    arguments: dict[str, Any] = {}
    reason: str = ""


class ToolResult(BaseModel):
    name: str
    status: Literal["success", "error", "denied"]
    data: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: int = 0


class ToolSpec(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any] = {}
    output_schema: dict[str, Any] = {}
    readonly: bool = True
    timeout_seconds: int = 30
    required_permissions: list[str] = []
    redaction_policy: str | None = None


class ValidationResult(BaseModel):
    valid: bool
    needs_clarification: bool = False
    missing_fields: list[str] = []
    clarification_question: str | None = None

from __future__ import annotations

from k8s_troubleshooter.harness.context import SessionContext
from k8s_troubleshooter.harness.schema import DiagnosisRequest, ValidationResult


SUPPORTED_KINDS = {"Pod", "Namespace"}
M1_ALLOWED_INTENTS = {"diagnose_pod", "diagnose_namespace", "explain_finding"}


def validate_request(
    request: DiagnosisRequest, session: SessionContext | None = None
) -> ValidationResult:
    missing: list[str] = []

    if request.intent == "diagnose_workload":
        return ValidationResult(
            valid=False,
            needs_clarification=True,
            clarification_question="当前版本不支持 Workload 级别诊断，请指定 Pod 或 Namespace。",
        )

    if request.intent not in M1_ALLOWED_INTENTS:
        return ValidationResult(
            valid=False,
            needs_clarification=True,
            clarification_question=f"无法识别的操作类型: {request.intent}",
        )

    if request.mode != "readonly":
        return ValidationResult(
            valid=False,
            needs_clarification=False,
            missing_fields=["mode"],
            clarification_question="当前版本仅支持只读模式。",
        )

    if request.scope.kind not in SUPPORTED_KINDS:
        missing.append("scope.kind")

    if request.intent == "diagnose_pod":
        if not request.scope.namespace:
            missing.append("namespace")
        if not request.scope.name:
            missing.append("resource_name")

    if request.intent == "diagnose_namespace":
        if not request.scope.namespace:
            missing.append("namespace")

    if request.intent == "explain_finding":
        if session and not session.active_findings:
            return ValidationResult(
                valid=False,
                needs_clarification=True,
                clarification_question="当前没有可解释的诊断结果，请先进行一次诊断。",
            )

    if missing:
        parts = []
        if "namespace" in missing:
            parts.append("namespace")
        if "resource_name" in missing:
            parts.append("资源名称")
        question = f"请提供要排查的 {' 和 '.join(parts)}。"
        return ValidationResult(
            valid=False,
            needs_clarification=True,
            missing_fields=missing,
            clarification_question=question,
        )

    return ValidationResult(valid=True)

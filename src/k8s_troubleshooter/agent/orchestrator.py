from __future__ import annotations

import re
import uuid
from typing import Any

import logging

logger = logging.getLogger(__name__)

from k8s_troubleshooter.config import AppConfig
from k8s_troubleshooter.diagnosis.engine import DiagnosisEngine
from k8s_troubleshooter.diagnosis.llm_fallback import LLMFallbackDiagnoser
from k8s_troubleshooter.diagnosis.registry import load_diagnosers
from k8s_troubleshooter.evidence.model import Evidence, ResourceRef
from k8s_troubleshooter.harness.context import SessionContext
from k8s_troubleshooter.harness.executor import ToolExecutor
from k8s_troubleshooter.harness.policy import PolicyContext
from k8s_troubleshooter.harness.schema import (
    DiagnosisRequest,
    DiagnosisResult,
    ResourceScope,
    ToolCall,
)
from k8s_troubleshooter.llm.provider import LLMProvider

_REDACT_PATTERNS = [
    re.compile(r"(?i)(password|passwd|pwd|token|secret|api[_-]?key|access[_-]?key|credential)\s*[:=]\s*\S+"),
    re.compile(r"-----BEGIN\s+\w+[^-]*-----"),
]


def _redact_log_line(line: str) -> str:
    for pattern in _REDACT_PATTERNS:
        line = pattern.sub("[REDACTED]", line)
    return line


class DiagnosisOrchestrator:
    def __init__(
        self,
        tool_executor: ToolExecutor,
        llm_provider: LLMProvider | None,
        config: AppConfig,
        policy_guard=None,
    ) -> None:
        self._tool_executor = tool_executor
        self._config = config
        diagnosers = load_diagnosers()
        llm_fallback = LLMFallbackDiagnoser(llm_provider, policy_guard)
        self._engine = DiagnosisEngine(diagnosers, llm_fallback)

    async def diagnose(
        self, request: DiagnosisRequest, session: SessionContext
    ) -> DiagnosisResult:
        trace_id = f"diag-{uuid.uuid4().hex[:12]}"

        if request.intent == "diagnose_pod":
            return await self._diagnose_pod(request, session, trace_id)
        elif request.intent == "diagnose_namespace":
            return await self._diagnose_namespace(request, session, trace_id)
        elif request.intent == "explain_finding":
            return await self._explain_finding(request, session, trace_id)
        else:
            return DiagnosisResult(
                request=request,
                resource=ResourceRef(
                    kind="Unknown",
                    namespace=request.scope.namespace or "",
                    name=request.scope.name or "",
                ),
                status="unsupported",
                findings=[],
                trace_id=trace_id,
            )

    async def _diagnose_pod(
        self,
        request: DiagnosisRequest,
        session: SessionContext,
        trace_id: str,
    ) -> DiagnosisResult:
        ns = request.scope.namespace or ""
        name = request.scope.name or ""
        policy_ctx = PolicyContext()

        tool_plan = [
            ToolCall(name="get_pod", arguments={"namespace": ns, "name": name}, reason="Get Pod details"),
        ]

        results = await self._tool_executor.execute_plan(tool_plan, policy_ctx)

        pod_result = results[0]
        if pod_result.status != "success" or not pod_result.data:
            return DiagnosisResult(
                request=request,
                resource=ResourceRef(kind="Pod", namespace=ns, name=name),
                status="error",
                findings=[],
                evidence_summary={"error": pod_result.error},
                trace_id=trace_id,
            )

        pod_data = pod_result.data
        container_names = pod_data.get("container_names", [name])
        init_container_names = pod_data.get("init_container_names", [])

        extra_tools = [
            ToolCall(
                name="get_pod_events",
                arguments={"namespace": ns, "name": name},
                reason="Get Pod events",
            ),
        ]

        all_containers = container_names + init_container_names
        for cn in all_containers:
            extra_tools.append(
                ToolCall(
                    name="get_container_logs",
                    arguments={"namespace": ns, "pod": name, "container": cn, "previous": False},
                    reason=f"Get current logs for {cn}",
                )
            )
            extra_tools.append(
                ToolCall(
                    name="get_container_logs",
                    arguments={"namespace": ns, "pod": name, "container": cn, "previous": True},
                    reason=f"Get previous logs for {cn}",
                )
            )

        owner_refs = pod_data.get("owner_references", [])
        if owner_refs:
            extra_tools.append(
                ToolCall(
                    name="get_owner_workload",
                    arguments={"namespace": ns, "owner_references": owner_refs},
                    reason="Get owner workload",
                )
            )

        # Dynamic tools based on Pod spec references
        for pvc_name in pod_data.get("pvc_refs", []):
            extra_tools.append(
                ToolCall(
                    name="get_pvc_metadata",
                    arguments={"namespace": ns, "name": pvc_name},
                    reason=f"Check PVC {pvc_name}",
                )
            )
        for cm_name in pod_data.get("configmap_refs", []):
            extra_tools.append(
                ToolCall(
                    name="check_configmap_exists",
                    arguments={"namespace": ns, "name": cm_name},
                    reason=f"Check ConfigMap {cm_name}",
                )
            )
        for secret_name in pod_data.get("secret_refs", []):
            extra_tools.append(
                ToolCall(
                    name="check_secret_exists",
                    arguments={"namespace": ns, "name": secret_name},
                    reason=f"Check Secret {secret_name}",
                )
            )

        extra_results = await self._tool_executor.execute_plan(extra_tools, policy_ctx)
        all_results = results + extra_results
        all_calls = tool_plan + extra_tools

        return await self._build_result(request, all_results, all_calls, trace_id, ns, name)

    async def _diagnose_namespace(
        self,
        request: DiagnosisRequest,
        session: SessionContext,
        trace_id: str,
    ) -> DiagnosisResult:
        ns = request.scope.namespace or ""
        policy_ctx = PolicyContext()

        list_result = await self._tool_executor.execute(
            ToolCall(name="list_pods", arguments={"namespace": ns}, reason="List all Pods"),
            policy_ctx,
        )

        if list_result.status != "success" or not list_result.data:
            return DiagnosisResult(
                request=request,
                resource=ResourceRef(kind="Namespace", namespace=ns, name=ns),
                status="error",
                findings=[],
                evidence_summary={"error": list_result.error},
                trace_id=trace_id,
            )

        pods = list_result.data.get("pods", [])
        unhealthy = [p for p in pods if self._is_unhealthy(p)]
        unhealthy = unhealthy[: self._config.max_pods_per_scan]

        all_findings = []
        for pod_info in unhealthy:
            pod_name = pod_info.get("name", "")
            pod_request = DiagnosisRequest(
                intent="diagnose_pod",
                scope=ResourceScope(kind="Pod", namespace=ns, name=pod_name),
            )
            pod_trace_id = f"{trace_id}-{pod_name}"
            result = await self._diagnose_pod(pod_request, session, pod_trace_id)
            all_findings.extend(result.findings)

        return DiagnosisResult(
            request=request,
            resource=ResourceRef(kind="Namespace", namespace=ns, name=ns),
            status=f"Scanned {len(pods)} pods, {len(unhealthy)} unhealthy",
            findings=all_findings,
            evidence_summary={
                "total_pods": len(pods),
                "unhealthy_pods": len(unhealthy),
                "scanned_pods": [p.get("name") for p in unhealthy],
            },
            trace_id=trace_id,
        )

    async def _explain_finding(
        self,
        request: DiagnosisRequest,
        session: SessionContext,
        trace_id: str,
    ) -> DiagnosisResult:
        if not session.active_findings:
            return DiagnosisResult(
                request=request,
                resource=ResourceRef(
                    kind="Unknown",
                    namespace="",
                    name="",
                ),
                status="no_findings",
                findings=[],
                trace_id=trace_id,
            )

        from k8s_troubleshooter.diagnosis.finding import Finding, EvidenceItem

        findings = session.active_findings

        # Try to get current Pod status for context
        last_resource = session.last_diagnosed_resources[-1] if session.last_diagnosed_resources else None
        extra_evidence: list[EvidenceItem] = []
        if last_resource and last_resource.kind == "Pod":
            policy_ctx = PolicyContext()
            try:
                pod_result = await self._tool_executor.execute(
                    ToolCall(
                        name="get_pod",
                        arguments={"namespace": last_resource.namespace, "name": last_resource.name},
                        reason="Get current Pod status for explanation",
                    ),
                    policy_ctx,
                )
                if pod_result.status == "success" and pod_result.data:
                    phase = pod_result.data.get("phase", "Unknown")
                    extra_evidence.append(EvidenceItem(
                        source="current_pod_status",
                        message=f"Current phase: {phase}",
                    ))
            except Exception as e:
                logger.debug("Failed to get current Pod status for explanation: %s", e)

        # Build explanation via engine's LLM fallback
        explained_findings = []
        for f in findings:
            explained = f.model_copy()
            if extra_evidence:
                explained.evidence = list(explained.evidence) + extra_evidence
            explained_findings.append(explained)

        return DiagnosisResult(
            request=request,
            resource=last_resource or ResourceRef(kind="Finding", namespace="", name=""),
            status="explained",
            findings=explained_findings,
            evidence_summary={"explained_findings": [f.type for f in findings]},
            trace_id=trace_id,
        )

    async def _build_result(
        self,
        request: DiagnosisRequest,
        tool_results: list,
        tool_calls: list[ToolCall],
        trace_id: str,
        namespace: str,
        name: str,
    ) -> DiagnosisResult:
        # Extract data from tool results
        pod_data = None
        events_data = []
        logs_data: list[tuple[str, str]] = []
        workload_data = None
        related_resources: list[dict] = []

        # Build a map from tool name to its call arguments for result correlation
        call_args_by_index: dict[int, dict] = {}
        for i, tc in enumerate(tool_calls):
            call_args_by_index[i] = tc.arguments

        for i, r in enumerate(tool_results):
            if r.status != "success" or not r.data:
                continue
            if r.name == "get_pod":
                pod_data = r.data
            elif r.name == "get_pod_events":
                events_data = r.data.get("events", [])
            elif r.name == "get_container_logs":
                container = r.data.get("container", "")
                log_text = r.data.get("logs", "")
                logs_data.append((container, log_text))
            elif r.name == "get_owner_workload":
                workload_data = r.data
            elif r.name == "get_pvc_metadata":
                args = call_args_by_index.get(i, {})
                related_resources.append({
                    "kind": "PersistentVolumeClaim",
                    "name": args.get("name", ""),
                    "data": r.data,
                })
            elif r.name == "check_configmap_exists":
                args = call_args_by_index.get(i, {})
                related_resources.append({
                    "kind": "ConfigMap",
                    "name": args.get("name", ""),
                    "data": r.data,
                })
            elif r.name == "check_secret_exists":
                args = call_args_by_index.get(i, {})
                related_resources.append({
                    "kind": "Secret",
                    "name": args.get("name", ""),
                    "data": r.data,
                })

        if not pod_data:
            return DiagnosisResult(
                request=request,
                resource=ResourceRef(kind="Pod", namespace=namespace, name=name),
                status="no_pod_data",
                findings=[],
                trace_id=trace_id,
            )

        # We need a V1Pod to build evidence, but we have dict data
        # Use the dict-based evidence building instead
        from k8s_troubleshooter.evidence.model import (
            ContainerStatusEvidence,
            EventEvidence,
            LogEvidence,
            PodEvidence,
            WorkloadEvidence,
        )

        pod_evidence = PodEvidence(
            namespace=namespace,
            name=name,
            uid=pod_data.get("uid"),
            phase=pod_data.get("phase", "Unknown"),
            conditions=pod_data.get("conditions", []),
            container_statuses=[
                ContainerStatusEvidence(**cs)
                for cs in pod_data.get("container_statuses", [])
            ],
            init_container_statuses=[
                ContainerStatusEvidence(**cs)
                for cs in pod_data.get("init_container_statuses", [])
            ],
            qos_class=pod_data.get("qos_class", ""),
            node_name=pod_data.get("node_name"),
            owner_references=pod_data.get("owner_references", []),
            resource_requests=pod_data.get("resource_requests", {}),
            resource_limits=pod_data.get("resource_limits", {}),
            configmap_refs=pod_data.get("configmap_refs", []),
            secret_refs=pod_data.get("secret_refs", []),
            pvc_refs=pod_data.get("pvc_refs", []),
            service_account_name=pod_data.get("service_account_name", ""),
            image_pull_secrets=pod_data.get("image_pull_secrets", []),
            node_selector=pod_data.get("node_selector", {}),
            tolerations=pod_data.get("tolerations", []),
        )

        event_evidence = [
            EventEvidence(**e) for e in events_data
        ]

        log_evidence = []
        for container, logs in logs_data:
            lines = logs.splitlines() if logs else []
            redacted_lines = [_redact_log_line(line) for line in lines]
            log_evidence.append(LogEvidence(
                container=container,
                lines=redacted_lines,
                truncated="[truncated]" in (logs or ""),
                redacted=any(r != o for r, o in zip(redacted_lines, lines)),
            ))

        workload_evidence = None
        if workload_data:
            workload_evidence = WorkloadEvidence(**workload_data)

        # Build related resources from PVC/CM/Secret checks
        extra_related: list[ResourceRef] = []
        for rr in related_resources:
            rr_data = rr["data"]
            if rr_data.get("exists", True):
                extra_related.append(ResourceRef(
                    kind=rr["kind"],
                    namespace=namespace,
                    name=rr["name"],
                ))

        evidence = Evidence(
            resource=ResourceRef(kind="Pod", namespace=namespace, name=name),
            pod=pod_evidence,
            events=event_evidence,
            logs=log_evidence,
            workload=workload_evidence,
            related_resources=extra_related,
        )

        findings = await self._engine.diagnose(evidence, request)

        return DiagnosisResult(
            request=request,
            resource=ResourceRef(kind="Pod", namespace=namespace, name=name),
            status=pod_data.get("phase"),
            findings=findings,
            evidence_summary={"phase": pod_data.get("phase")},
            trace_id=trace_id,
        )

    @staticmethod
    def _is_unhealthy(pod_info: dict) -> bool:
        phase = pod_info.get("phase", "")
        if phase not in ("Running", "Succeeded"):
            return True
        for cs in pod_info.get("container_statuses", []):
            if not cs.get("ready", True):
                return True
            if cs.get("restart_count", 0) > 5:
                return True
            if cs.get("waiting_reason"):
                return True
        return False

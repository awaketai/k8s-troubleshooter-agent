from __future__ import annotations

import re
from typing import Any

from kubernetes.client import CoreV1Event, V1ContainerState, V1Pod

from k8s_troubleshooter.evidence.model import (
    ContainerStatusEvidence,
    EventEvidence,
    Evidence,
    LogEvidence,
    PodEvidence,
    ResourceRef,
    WorkloadEvidence,
)


def _extract_container_status(cs: Any) -> ContainerStatusEvidence:
    state = "unknown"
    waiting_reason = None
    waiting_message = None
    terminated_reason = None
    terminated_message = None
    terminated_exit_code = None

    if cs.state:
        if cs.state.waiting:
            state = "waiting"
            waiting_reason = cs.state.waiting.reason
            waiting_message = cs.state.waiting.message
        elif cs.state.running:
            state = "running"
        elif cs.state.terminated:
            state = "terminated"
            terminated_reason = cs.state.terminated.reason
            terminated_message = cs.state.terminated.message
            terminated_exit_code = cs.state.terminated.exit_code

    resources_requests = {}
    resources_limits = {}
    if cs.resources and cs.resources.requests:
        resources_requests = {k: str(v) for k, v in cs.resources.requests.items()}
    if cs.resources and cs.resources.limits:
        resources_limits = {k: str(v) for k, v in cs.resources.limits.items()}

    liveness_probe = None
    readiness_probe = None
    startup_probe = None

    return ContainerStatusEvidence(
        name=cs.name,
        ready=cs.ready or False,
        state=state,
        waiting_reason=waiting_reason,
        waiting_message=waiting_message,
        terminated_reason=terminated_reason,
        terminated_message=terminated_message,
        terminated_exit_code=terminated_exit_code,
        restart_count=cs.restart_count or 0,
        image=cs.image or "",
        image_id=cs.image_id or "",
        resources_requests=resources_requests,
        resources_limits=resources_limits,
    )


def _extract_probe(probe: Any) -> dict | None:
    if not probe:
        return None
    result: dict = {}
    if probe.http_get:
        result["type"] = "httpGet"
        result["path"] = probe.http_get.path
        result["port"] = probe.http_get.port
    elif probe.tcp_socket:
        result["type"] = "tcpSocket"
        result["port"] = probe.tcp_socket.port
    elif probe.exec:
        result["type"] = "exec"
        result["command"] = probe.exec.command
    result["initialDelaySeconds"] = probe.initial_delay_seconds or 0
    result["timeoutSeconds"] = probe.timeout_seconds or 1
    result["periodSeconds"] = probe.period_seconds or 10
    result["failureThreshold"] = probe.failure_threshold or 3
    return result


def normalize_pod(pod: V1Pod) -> PodEvidence:
    metadata = pod.metadata
    spec = pod.spec
    status = pod.status

    container_statuses = []
    init_container_statuses = []

    if status and status.container_statuses:
        container_statuses = [_extract_container_status(cs) for cs in status.container_statuses]
    if status and status.init_container_statuses:
        init_container_statuses = [_extract_container_status(cs) for cs in status.init_container_statuses]

    owner_refs = []
    if metadata and metadata.owner_references:
        owner_refs = [
            {
                "api_version": ref.api_version,
                "kind": ref.kind,
                "name": ref.name,
                "uid": ref.uid,
            }
            for ref in metadata.owner_references
        ]

    configmap_refs = []
    secret_refs = []
    pvc_refs = []
    image_pull_secrets = []
    node_selector = {}
    node_affinity = None
    tolerations = []
    service_account_name = ""

    if spec:
        for vol in spec.volumes or []:
            if vol.config_map and vol.config_map.name:
                configmap_refs.append(vol.config_map.name)
            if vol.secret and vol.secret.secret_name:
                secret_refs.append(vol.secret.secret_name)
            if vol.persistent_volume_claim and vol.persistent_volume_claim.claim_name:
                pvc_refs.append(vol.persistent_volume_claim.claim_name)

        for container in spec.containers:
            for env_var in container.env or []:
                if env_var.value_from:
                    if env_var.value_from.config_map_key_ref:
                        configmap_refs.append(env_var.value_from.config_map_key_ref.name)
                    if env_var.value_from.secret_key_ref:
                        secret_refs.append(env_var.value_from.secret_key_ref.name)
            for env_from in container.env_from or []:
                if env_from.config_map_ref and env_from.config_map_ref.name:
                    configmap_refs.append(env_from.config_map_ref.name)
                if env_from.secret_ref and env_from.secret_ref.name:
                    secret_refs.append(env_from.secret_ref.name)

        if spec.image_pull_secrets:
            image_pull_secrets = [ips.name for ips in spec.image_pull_secrets if ips.name]
        if spec.node_selector:
            node_selector = dict(spec.node_selector)
        if spec.affinity and spec.affinity.node_affinity:
            na = spec.affinity.node_affinity
            node_affinity = {}
            if na.required_during_scheduling_ignored_during_execution:
                terms = na.required_during_scheduling_ignored_during_execution.node_selector_terms or []
                node_affinity["required"] = [
                    {
                        "matchExpressions": [
                            {"key": e.key, "operator": e.operator, "values": e.values or []}
                            for e in (term.match_expressions or [])
                        ],
                        "matchFields": [
                            {"key": f.key, "operator": f.operator, "values": f.values or []}
                            for f in (term.match_fields or [])
                        ],
                    }
                    for term in terms
                ]
            if na.preferred_during_scheduling_ignored_during_execution:
                node_affinity["preferred"] = [
                    {
                        "weight": p.weight,
                        "preference": {
                            "matchExpressions": [
                                {"key": e.key, "operator": e.operator, "values": e.values or []}
                                for e in (p.preference.match_expressions or [])
                            ],
                        },
                    }
                    for p in na.preferred_during_scheduling_ignored_during_execution
                ]
        if spec.tolerations:
            tolerations = [
                {
                    "key": t.key,
                    "operator": t.operator,
                    "value": t.value,
                    "effect": t.effect,
                }
                for t in spec.tolerations
            ]
        service_account_name = spec.service_account_name or ""

    # Extract probe info into container statuses
    if spec:
        for i, container in enumerate(spec.containers):
            if i < len(container_statuses):
                container_statuses[i].liveness_probe = _extract_probe(container.liveness_probe)
                container_statuses[i].readiness_probe = _extract_probe(container.readiness_probe)
                container_statuses[i].startup_probe = _extract_probe(container.startup_probe)

    resource_requests = {}
    resource_limits = {}
    if spec:
        for container in spec.containers:
            if container.resources and container.resources.requests:
                for k, v in container.resources.requests.items():
                    resource_requests[k] = str(v)
            if container.resources and container.resources.limits:
                for k, v in container.resources.limits.items():
                    resource_limits[k] = str(v)

    return PodEvidence(
        namespace=metadata.namespace if metadata else "",
        name=metadata.name if metadata else "",
        uid=metadata.uid if metadata else None,
        phase=status.phase if status else "Unknown",
        conditions=[
            {
                "type": c.type,
                "status": c.status,
                "reason": c.reason,
                "message": c.message,
            }
            for c in (status.conditions or [])
            if status
        ],
        init_container_statuses=init_container_statuses,
        container_statuses=container_statuses,
        qos_class=status.qos_class if status else "",
        node_name=spec.node_name if spec else None,
        owner_references=owner_refs,
        resource_requests=resource_requests,
        resource_limits=resource_limits,
        configmap_refs=list(set(configmap_refs)),
        secret_refs=list(set(secret_refs)),
        pvc_refs=list(set(pvc_refs)),
        service_account_name=service_account_name,
        image_pull_secrets=image_pull_secrets,
        node_selector=node_selector,
        node_affinity=node_affinity,
        tolerations=tolerations,
    )


def normalize_events(events: list[CoreV1Event]) -> list[EventEvidence]:
    result = []
    for e in events:
        result.append(
            EventEvidence(
                reason=e.reason or "",
                message=e.message or "",
                count=e.count or 1,
                last_timestamp=str(e.last_timestamp) if e.last_timestamp else None,
                type=e.type or "",
                source_component=(
                    e.source.component if e.source else ""
                ),
            )
        )
    return result


_SENSITIVE_PATTERNS = [
    re.compile(r"(?i)(password|passwd|pwd|token|secret|api[_-]?key|access[_-]?key|credential)\s*[:=]\s*\S+"),
    re.compile(r"-----BEGIN\s+\w+[^-]*-----"),
]


def _redact_line(line: str) -> str:
    for pattern in _SENSITIVE_PATTERNS:
        line = pattern.sub("[REDACTED]", line)
    return line


def normalize_logs(raw_logs: str, container: str) -> LogEvidence:
    if not raw_logs or raw_logs.startswith("[LOG_UNAVAILABLE]"):
        return LogEvidence(
            container=container,
            lines=[raw_logs] if raw_logs else [],
            truncated=False,
            redacted=False,
        )

    lines = raw_logs.splitlines()
    truncated = "[truncated]" in raw_logs
    redacted_lines = [_redact_line(line) for line in lines]
    was_redacted = any(r != o for r, o in zip(redacted_lines, lines))

    return LogEvidence(
        container=container,
        lines=redacted_lines,
        truncated=truncated,
        redacted=was_redacted,
    )


def normalize_workload(workload_obj: dict[str, Any] | None) -> WorkloadEvidence | None:
    if not workload_obj:
        return None
    return WorkloadEvidence(
        kind=workload_obj.get("kind", ""),
        name=workload_obj.get("name", ""),
        replicas=workload_obj.get("replicas"),
        ready_replicas=workload_obj.get("ready_replicas"),
        conditions=workload_obj.get("conditions", []),
    )


def build_evidence(
    pod: V1Pod,
    events: list[CoreV1Event],
    logs: list[tuple[str, str]],
    workload: dict[str, Any] | None,
) -> Evidence:
    pod_evidence = normalize_pod(pod)
    metadata = pod.metadata

    resource_ref = ResourceRef(
        kind="Pod",
        namespace=metadata.namespace if metadata else "",
        name=metadata.name if metadata else "",
        uid=metadata.uid if metadata else None,
    )

    event_evidence = normalize_events(events)
    log_evidence = [normalize_logs(log_text, container) for container, log_text in logs]
    workload_evidence = normalize_workload(workload)

    related = []
    if workload_evidence:
        related.append(
            ResourceRef(
                kind=workload_evidence.kind,
                namespace=pod_evidence.namespace,
                name=workload_evidence.name,
            )
        )

    return Evidence(
        resource=resource_ref,
        pod=pod_evidence,
        events=event_evidence,
        logs=log_evidence,
        workload=workload_evidence,
        related_resources=related,
    )

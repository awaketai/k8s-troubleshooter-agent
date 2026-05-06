from __future__ import annotations

import logging
from typing import Any

from k8s_troubleshooter.config import AppConfig

logger = logging.getLogger(__name__)
from k8s_troubleshooter.harness.schema import ToolSpec
from k8s_troubleshooter.harness.tools import ToolRegistry
from k8s_troubleshooter.kube.client import KubeClient
from k8s_troubleshooter.kube.event_collector import EventCollector
from k8s_troubleshooter.kube.log_collector import LogCollector
from k8s_troubleshooter.kube.pod_collector import PodCollector
from k8s_troubleshooter.kube.workload_collector import WorkloadCollector


def register_m1_tools(
    registry: ToolRegistry, kube_client: KubeClient, config: AppConfig
) -> None:
    pod_collector = PodCollector(kube_client)
    event_collector = EventCollector(kube_client)
    log_collector = LogCollector(kube_client)
    workload_collector = WorkloadCollector(kube_client)

    registry.register(
        ToolSpec(
            name="list_pods",
            description="List all Pods in a namespace",
            readonly=True,
            timeout_seconds=15,
        ),
        _make_list_pods(pod_collector),
    )

    registry.register(
        ToolSpec(
            name="get_pod",
            description="Get Pod details",
            readonly=True,
            timeout_seconds=10,
        ),
        _make_get_pod(pod_collector),
    )

    registry.register(
        ToolSpec(
            name="get_pod_events",
            description="Get events for a Pod",
            readonly=True,
            timeout_seconds=10,
        ),
        _make_get_pod_events(event_collector),
    )

    registry.register(
        ToolSpec(
            name="get_container_logs",
            description="Get container logs",
            readonly=True,
            timeout_seconds=15,
        ),
        _make_get_container_logs(log_collector, config),
    )

    registry.register(
        ToolSpec(
            name="get_owner_workload",
            description="Get owner workload for a Pod",
            readonly=True,
            timeout_seconds=10,
        ),
        _make_get_owner_workload(workload_collector),
    )

    registry.register(
        ToolSpec(
            name="get_pvc_metadata",
            description="Get PVC metadata",
            readonly=True,
            timeout_seconds=10,
        ),
        _make_get_pvc_metadata(kube_client),
    )

    registry.register(
        ToolSpec(
            name="check_configmap_exists",
            description="Check if ConfigMap exists and return keys",
            readonly=True,
            timeout_seconds=10,
        ),
        _make_check_configmap_exists(kube_client),
    )

    registry.register(
        ToolSpec(
            name="check_secret_exists",
            description="Check if Secret exists (returns type and keys only, no values)",
            readonly=True,
            timeout_seconds=10,
        ),
        _make_check_secret_exists(kube_client),
    )


def _make_list_pods(collector: PodCollector):
    async def handler(namespace: str, **kwargs) -> dict:
        pods = await collector.list_pods(namespace)
        result = []
        for pod in pods:
            container_statuses = []
            if pod.status and pod.status.container_statuses:
                for cs in pod.status.container_statuses:
                    state = "unknown"
                    waiting_reason = None
                    terminated_reason = None
                    terminated_exit_code = None
                    if cs.state:
                        if cs.state.waiting:
                            state = "waiting"
                            waiting_reason = cs.state.waiting.reason
                        elif cs.state.running:
                            state = "running"
                        elif cs.state.terminated:
                            state = "terminated"
                            terminated_reason = cs.state.terminated.reason
                            terminated_exit_code = cs.state.terminated.exit_code
                    container_statuses.append({
                        "name": cs.name,
                        "ready": cs.ready or False,
                        "state": state,
                        "waiting_reason": waiting_reason,
                        "terminated_reason": terminated_reason,
                        "terminated_exit_code": terminated_exit_code,
                        "restart_count": cs.restart_count or 0,
                        "image": cs.image or "",
                    })
            result.append({
                "name": pod.metadata.name if pod.metadata else "",
                "namespace": pod.metadata.namespace if pod.metadata else "",
                "phase": pod.status.phase if pod.status else "Unknown",
                "container_statuses": container_statuses,
            })
        return {"pods": result}
    return handler


def _make_get_pod(collector: PodCollector):
    async def handler(namespace: str, name: str, **kwargs) -> dict:
        from k8s_troubleshooter.evidence.normalizer import normalize_pod
        pod = await collector.get_pod(namespace, name)
        pod_ev = normalize_pod(pod)
        return pod_ev.model_dump()
    return handler


def _make_get_pod_events(collector: EventCollector):
    async def handler(namespace: str, name: str, **kwargs) -> dict:
        from k8s_troubleshooter.evidence.normalizer import normalize_events
        events = await collector.get_events(namespace, involved_object_name=name, involved_object_kind="Pod")
        event_list = normalize_events(events)
        return {"events": [e.model_dump() for e in event_list]}
    return handler


def _make_get_container_logs(collector: LogCollector, config: AppConfig):
    async def handler(namespace: str, pod: str, container: str, previous: bool = False, **kwargs) -> dict:
        logs = await collector.get_logs(
            namespace=namespace,
            pod=pod,
            container=container,
            previous=previous,
            tail_lines=config.log_tail_lines,
        )
        return {"container": container, "logs": logs}
    return handler


def _make_get_owner_workload(collector: WorkloadCollector):
    async def handler(namespace: str, owner_references: list, **kwargs) -> dict:
        result = await collector.get_owner_workload(namespace, owner_references)
        return result or {}
    return handler


def _make_get_pvc_metadata(kube_client: KubeClient):
    async def handler(namespace: str, name: str, **kwargs) -> dict:
        import asyncio
        try:
            pvc = await asyncio.to_thread(
                kube_client.core_v1.read_namespaced_persistent_volume_claim,
                name,
                namespace,
            )
            return {
                "exists": True,
                "phase": pvc.status.phase if pvc.status else "Unknown",
                "access_modes": pvc.spec.access_modes if pvc.spec else [],
                "storage_class_name": pvc.spec.storage_class_name if pvc.spec else None,
            }
        except Exception as e:
            logger.debug("PVC %s/%s not found: %s", namespace, name, e)
            return {"exists": False}
    return handler


def _make_check_configmap_exists(kube_client: KubeClient):
    async def handler(namespace: str, name: str, **kwargs) -> dict:
        import asyncio
        try:
            cm = await asyncio.to_thread(
                kube_client.core_v1.read_namespaced_config_map,
                name,
                namespace,
            )
            return {
                "exists": True,
                "keys": list(cm.data.keys()) if cm.data else [],
            }
        except Exception as e:
            logger.debug("ConfigMap %s/%s not found: %s", namespace, name, e)
            return {"exists": False, "keys": []}
    return handler


def _make_check_secret_exists(kube_client: KubeClient):
    async def handler(namespace: str, name: str, **kwargs) -> dict:
        import asyncio
        try:
            secret = await asyncio.to_thread(
                kube_client.core_v1.read_namespaced_secret,
                name,
                namespace,
            )
            # Security: only return metadata, never return .data
            return {
                "exists": True,
                "type": secret.type or "Opaque",
                "keys": list(secret.data.keys()) if secret.data else [],
            }
        except Exception as e:
            logger.debug("Secret %s/%s not found: %s", namespace, name, e)
            return {"exists": False, "type": None, "keys": []}
    return handler

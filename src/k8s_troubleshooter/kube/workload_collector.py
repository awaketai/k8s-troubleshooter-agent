from __future__ import annotations

import asyncio
from typing import Any

from k8s_troubleshooter.kube.client import KubeClient


class WorkloadCollector:
    def __init__(self, kube_client: KubeClient) -> None:
        self._client = kube_client

    async def get_owner_workload(
        self, namespace: str, owner_references: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        if not owner_references:
            return None

        ref = owner_references[0]
        kind = ref.get("kind", "")
        name = ref.get("name", "")

        if kind == "ReplicaSet":
            rs = await asyncio.to_thread(
                self._client.apps_v1.read_namespaced_replica_set,
                name,
                namespace,
            )
            rs_info: dict[str, Any] = {
                "kind": "ReplicaSet",
                "name": name,
                "replicas": rs.spec.replicas if rs.spec else 0,
                "ready_replicas": rs.status.ready_replicas if rs.status else 0,
            }
            if rs.metadata and rs.metadata.owner_references:
                deploy_ref = rs.metadata.owner_references[0]
                if deploy_ref.kind == "Deployment":
                    deploy = await asyncio.to_thread(
                        self._client.apps_v1.read_namespaced_deployment,
                        deploy_ref.name,
                        namespace,
                    )
                    return {
                        "kind": "Deployment",
                        "name": deploy_ref.name,
                        "replicas": deploy.spec.replicas if deploy.spec else 0,
                        "ready_replicas": deploy.status.ready_replicas
                        if deploy.status
                        else 0,
                        "conditions": [
                            {
                                "type": c.type,
                                "status": c.status,
                                "reason": c.reason,
                                "message": c.message,
                            }
                            for c in (deploy.status.conditions or [])
                        ] if deploy.status else [],
                    }
            return rs_info

        if kind == "StatefulSet":
            sts = await asyncio.to_thread(
                self._client.apps_v1.read_namespaced_stateful_set,
                name,
                namespace,
            )
            return {
                "kind": "StatefulSet",
                "name": name,
                "replicas": sts.spec.replicas if sts.spec else 0,
                "ready_replicas": sts.status.ready_replicas if sts.status else 0,
            }

        if kind == "DaemonSet":
            ds = await asyncio.to_thread(
                self._client.apps_v1.read_namespaced_daemon_set,
                name,
                namespace,
            )
            desired = ds.status.desired_number_scheduled if ds.status else 0
            ready = ds.status.number_ready if ds.status else 0
            return {
                "kind": "DaemonSet",
                "name": name,
                "replicas": desired,
                "ready_replicas": ready,
                "conditions": [
                    {
                        "type": c.type,
                        "status": c.status,
                        "reason": c.reason,
                        "message": c.message,
                    }
                    for c in (ds.status.conditions or [])
                ] if ds.status else [],
            }

        return None

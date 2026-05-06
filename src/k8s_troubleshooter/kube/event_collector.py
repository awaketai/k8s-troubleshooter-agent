from __future__ import annotations

import asyncio

from kubernetes.client import CoreV1Event

from k8s_troubleshooter.kube.client import KubeClient


class EventCollector:
    def __init__(self, kube_client: KubeClient) -> None:
        self._client = kube_client

    async def get_events(
        self,
        namespace: str,
        involved_object_name: str | None = None,
        involved_object_kind: str | None = None,
        limit: int = 50,
    ) -> list[CoreV1Event]:
        resp = await asyncio.to_thread(
            self._client.core_v1.list_namespaced_event,
            namespace,
        )
        events = resp.items or []

        if involved_object_name and involved_object_kind:
            events = [
                e
                for e in events
                if e.involved_object
                and e.involved_object.name == involved_object_name
                and e.involved_object.kind == involved_object_kind
            ]

        events.sort(
            key=lambda e: str(e.last_timestamp or e.event_time or ""),
            reverse=True,
        )
        return events[:limit]

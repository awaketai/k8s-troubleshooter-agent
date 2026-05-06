from __future__ import annotations

import asyncio

from k8s_troubleshooter.kube.client import KubeClient


class LogCollector:
    MAX_BYTES = 512 * 1024  # 512KB

    def __init__(self, kube_client: KubeClient) -> None:
        self._client = kube_client

    async def get_logs(
        self,
        namespace: str,
        pod: str,
        container: str,
        previous: bool = False,
        tail_lines: int = 200,
    ) -> str:
        try:
            logs = await asyncio.to_thread(
                self._client.core_v1.read_namespaced_pod_log,
                name=pod,
                namespace=namespace,
                container=container,
                previous=previous,
                tail_lines=tail_lines,
            )
            if len(logs.encode("utf-8", errors="replace")) > self.MAX_BYTES:
                logs = logs[: self.MAX_BYTES // 2] + "\n... [truncated] ...\n"
            return logs
        except Exception as e:
            return f"[LOG_UNAVAILABLE] {e}"

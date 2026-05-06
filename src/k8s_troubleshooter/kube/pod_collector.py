from __future__ import annotations

import asyncio
from typing import Any

from kubernetes.client import V1Pod

from k8s_troubleshooter.kube.client import KubeClient


class PodCollector:
    def __init__(self, kube_client: KubeClient) -> None:
        self._client = kube_client

    async def list_pods(self, namespace: str) -> list[V1Pod]:
        resp = await asyncio.to_thread(
            self._client.core_v1.list_namespaced_pod, namespace
        )
        return resp.items

    async def get_pod(self, namespace: str, name: str) -> V1Pod:
        return await asyncio.to_thread(
            self._client.core_v1.read_namespaced_pod, name, namespace
        )

    @staticmethod
    def extract_configmap_refs(pod: V1Pod) -> list[str]:
        refs: list[str] = []
        if not pod.spec:
            return refs
        for vol in pod.spec.volumes or []:
            if vol.config_map and vol.config_map.name:
                refs.append(vol.config_map.name)
        for container in pod.spec.containers:
            for env_var in container.env or []:
                if env_var.value_from and env_var.value_from.config_map_key_ref:
                    refs.append(env_var.value_from.config_map_key_ref.name)
            for env_from in container.env_from or []:
                if env_from.config_map_ref and env_from.config_map_ref.name:
                    refs.append(env_from.config_map_ref.name)
        return list(set(refs))

    @staticmethod
    def extract_secret_refs(pod: V1Pod) -> list[str]:
        refs: list[str] = []
        if not pod.spec:
            return refs
        for vol in pod.spec.volumes or []:
            if vol.secret and vol.secret.secret_name:
                refs.append(vol.secret.secret_name)
        for container in pod.spec.containers:
            for env_var in container.env or []:
                if env_var.value_from and env_var.value_from.secret_key_ref:
                    refs.append(env_var.value_from.secret_key_ref.name)
            for env_from in container.env_from or []:
                if env_from.secret_ref and env_from.secret_ref.name:
                    refs.append(env_from.secret_ref.name)
        if pod.spec.image_pull_secrets:
            for ips in pod.spec.image_pull_secrets:
                if ips.name:
                    refs.append(ips.name)
        return list(set(refs))

    @staticmethod
    def extract_pvc_refs(pod: V1Pod) -> list[str]:
        refs: list[str] = []
        if not pod.spec:
            return refs
        for vol in pod.spec.volumes or []:
            if vol.persistent_volume_claim and vol.persistent_volume_claim.claim_name:
                refs.append(vol.persistent_volume_claim.claim_name)
        return refs

    @staticmethod
    def extract_owner_references(pod: V1Pod) -> list[dict[str, Any]]:
        if not pod.metadata or not pod.metadata.owner_references:
            return []
        return [
            {
                "api_version": ref.api_version,
                "kind": ref.kind,
                "name": ref.name,
                "uid": ref.uid,
            }
            for ref in pod.metadata.owner_references
        ]

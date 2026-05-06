from __future__ import annotations

from kubernetes import client, config as kube_config
from kubernetes.client import ApiClient, AppsV1Api, CoreV1Api

from k8s_troubleshooter.config import AppConfig


class KubeClient:
    def __init__(self, app_config: AppConfig) -> None:
        self._config = app_config
        self._api_client: ApiClient | None = None
        self._core_v1: CoreV1Api | None = None
        self._apps_v1: AppsV1Api | None = None

    def _load(self) -> None:
        if self._core_v1 is not None:
            return
        kube_config.load_kube_config(
            config_file=self._config.resolved_kubeconfig,
            context=self._config.context,
        )
        self._api_client = ApiClient()
        self._core_v1 = CoreV1Api(self._api_client)
        self._apps_v1 = AppsV1Api(self._api_client)

    @property
    def core_v1(self) -> CoreV1Api:
        self._load()
        return self._core_v1  # type: ignore[return-value]

    @property
    def apps_v1(self) -> AppsV1Api:
        self._load()
        return self._apps_v1  # type: ignore[return-value]

    def verify_connection(self) -> None:
        try:
            self._load()
            self.core_v1.list_namespace(limit=1)
        except Exception as e:
            raise ConnectionError(
                f"Failed to connect to Kubernetes cluster: {e}"
            ) from e

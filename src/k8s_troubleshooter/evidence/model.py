from __future__ import annotations

from pydantic import BaseModel


class ResourceRef(BaseModel):
    kind: str
    namespace: str
    name: str
    uid: str | None = None


class ContainerStatusEvidence(BaseModel):
    name: str
    ready: bool = False
    state: str = "unknown"  # running, waiting, terminated, unknown
    waiting_reason: str | None = None
    waiting_message: str | None = None
    terminated_reason: str | None = None
    terminated_message: str | None = None
    terminated_exit_code: int | None = None
    restart_count: int = 0
    image: str = ""
    image_id: str = ""
    command: list[str] = []
    args: list[str] = []
    ports: list[int] = []
    resources_requests: dict[str, str] = {}
    resources_limits: dict[str, str] = {}
    liveness_probe: dict | None = None
    readiness_probe: dict | None = None
    startup_probe: dict | None = None


class PodEvidence(BaseModel):
    namespace: str
    name: str
    uid: str | None = None
    phase: str = "Unknown"
    conditions: list[dict] = []
    init_container_statuses: list[ContainerStatusEvidence] = []
    container_statuses: list[ContainerStatusEvidence] = []
    qos_class: str = ""
    node_name: str | None = None
    owner_references: list[dict] = []
    resource_requests: dict[str, str] = {}
    resource_limits: dict[str, str] = {}
    configmap_refs: list[str] = []
    secret_refs: list[str] = []
    pvc_refs: list[str] = []
    service_account_name: str = ""
    image_pull_secrets: list[str] = []
    node_selector: dict[str, str] = {}
    node_affinity: dict | None = None
    tolerations: list[dict] = []


class EventEvidence(BaseModel):
    reason: str = ""
    message: str = ""
    count: int = 1
    last_timestamp: str | None = None
    type: str = ""
    source_component: str = ""


class LogEvidence(BaseModel):
    container: str
    lines: list[str] = []
    truncated: bool = False
    redacted: bool = False


class WorkloadEvidence(BaseModel):
    kind: str = ""
    name: str = ""
    replicas: int | None = None
    ready_replicas: int | None = None
    conditions: list[dict] = []


class Evidence(BaseModel):
    resource: ResourceRef
    pod: PodEvidence | None = None
    events: list[EventEvidence] = []
    logs: list[LogEvidence] = []
    workload: WorkloadEvidence | None = None
    related_resources: list[ResourceRef] = []

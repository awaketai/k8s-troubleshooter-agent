from __future__ import annotations

from k8s_troubleshooter.diagnosis.base import BaseDiagnoser
from k8s_troubleshooter.diagnosis.finding import EvidenceItem, Finding
from k8s_troubleshooter.diagnosis.registry import register_diagnoser
from k8s_troubleshooter.evidence.model import Evidence


@register_diagnoser("image_pull")
class ImagePullDiagnoser(BaseDiagnoser):
    def can_diagnose(self, evidence: Evidence) -> bool:
        if not evidence.pod:
            return False
        for cs in evidence.pod.container_statuses:
            if cs.waiting_reason in ("ImagePullBackOff", "ErrImagePull"):
                return True
        for cs in evidence.pod.init_container_statuses:
            if cs.waiting_reason in ("ImagePullBackOff", "ErrImagePull"):
                return True
        return False

    def diagnose(self, evidence: Evidence) -> list[Finding]:
        if not evidence.pod:
            return []

        findings: list[Finding] = []
        all_containers = evidence.pod.container_statuses + evidence.pod.init_container_statuses

        for cs in all_containers:
            if cs.waiting_reason not in ("ImagePullBackOff", "ErrImagePull"):
                continue

            items: list[EvidenceItem] = [
                EvidenceItem(
                    source="container_status",
                    message=f"Container {cs.name} is waiting: {cs.waiting_reason} - {cs.waiting_message}",
                )
            ]

            event_msgs = [e.message.lower() for e in evidence.events if e.message]

            if any(kw in m for kw in ("not found", "notfound", "not exist", "manifest unknown") for m in event_msgs):
                findings.append(Finding(
                    type="image_not_found",
                    title="Image not found",
                    severity="high",
                    confidence=0.95,
                    source="rule",
                    evidence=items + [EvidenceItem(source="event", message=m) for m in event_msgs if any(kw in m for kw in ("not found", "notfound"))],
                    root_cause=f"Image {cs.image} does not exist in the registry.",
                    recommendations=[
                        f"Check if image '{cs.image}' name and tag are correct.",
                        "Verify the image exists in the registry.",
                        "Check for typos in the image name or tag.",
                    ],
                ))
            elif any(kw in m for kw in ("unauthorized", "authentication required", "pull access denied") for m in event_msgs):
                items.append(EvidenceItem(source="event", message="pull access denied or unauthorized"))
                has_pull_secrets = bool(evidence.pod.image_pull_secrets)
                if not has_pull_secrets:
                    items.append(EvidenceItem(source="pod.spec", message="imagePullSecrets is not configured"))
                findings.append(Finding(
                    type="image_auth_failed",
                    title="Image registry authentication failed",
                    severity="high",
                    confidence=0.91,
                    source="rule",
                    evidence=items,
                    root_cause="The image appears to be hosted in a private registry, but the Pod does not have valid pull credentials.",
                    recommendations=[
                        "Create a docker-registry Secret in the same namespace.",
                        "Attach the Secret through pod.spec.imagePullSecrets or the ServiceAccount.",
                        "Retry the rollout after confirming registry permissions.",
                    ],
                ))
            elif any(kw in m for kw in ("timeout", "dns", "tls", "certificate", "connection refused") for m in event_msgs):
                findings.append(Finding(
                    type="image_registry_unreachable",
                    title="Image registry unreachable",
                    severity="high",
                    confidence=0.85,
                    source="rule",
                    evidence=items + [EvidenceItem(source="event", message=m) for m in event_msgs if any(kw in m for kw in ("timeout", "dns", "tls", "certificate", "connection refused"))],
                    root_cause=f"Cannot reach the image registry for {cs.image}. DNS, TLS, or network connectivity issue.",
                    recommendations=[
                        "Check node network connectivity to the registry.",
                        "Verify DNS resolution for the registry host.",
                        "Check TLS certificates if using a private registry.",
                    ],
                ))
            else:
                findings.append(Finding(
                    type="image_pull_failed",
                    title="Image pull failed",
                    severity="medium",
                    confidence=0.6,
                    source="rule",
                    evidence=items,
                    root_cause=f"Image pull failed for {cs.image}, but the specific cause is unclear.",
                    recommendations=[
                        f"Check image '{cs.image}' availability in the registry.",
                        "Check node network connectivity.",
                        "Review events for more details: kubectl describe pod.",
                    ],
                    needs_llm_analysis=True,
                ))

        return findings

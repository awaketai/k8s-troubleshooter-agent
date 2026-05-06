from __future__ import annotations

from k8s_troubleshooter.diagnosis.base import BaseDiagnoser
from k8s_troubleshooter.diagnosis.finding import EvidenceItem, Finding
from k8s_troubleshooter.diagnosis.registry import register_diagnoser
from k8s_troubleshooter.evidence.model import Evidence


@register_diagnoser("config_error")
class ConfigErrorDiagnoser(BaseDiagnoser):
    def can_diagnose(self, evidence: Evidence) -> bool:
        if not evidence.pod:
            return False
        for cs in evidence.pod.container_statuses + evidence.pod.init_container_statuses:
            if cs.waiting_reason in ("CreateContainerConfigError", "CreateContainerError"):
                return True
        return False

    def diagnose(self, evidence: Evidence) -> list[Finding]:
        if not evidence.pod:
            return []

        findings: list[Finding] = []
        all_containers = evidence.pod.container_statuses + evidence.pod.init_container_statuses

        for cs in all_containers:
            if cs.waiting_reason not in ("CreateContainerConfigError", "CreateContainerError"):
                continue

            items: list[EvidenceItem] = [
                EvidenceItem(
                    source="container_status",
                    message=f"Container {cs.name} waiting: {cs.waiting_reason} - {cs.waiting_message}",
                )
            ]

            event_msgs = [e.message for e in evidence.events if e.message]

            root_cause = f"Container {cs.name} configuration error."
            recommendations: list[str] = []
            confidence = 0.75

            for msg in event_msgs:
                msg_lower = msg.lower()
                if "configmap" in msg_lower:
                    items.append(EvidenceItem(source="event", message=msg))
                    if "not found" in msg_lower or "not exist" in msg_lower:
                        cm_name = self._extract_resource_name(msg, "configmap")
                        if cm_name:
                            root_cause = f"ConfigMap '{cm_name}' referenced by container {cs.name} does not exist."
                            confidence = 0.9
                            recommendations.extend([
                                f"Create ConfigMap '{cm_name}' in namespace '{evidence.pod.namespace}'.",
                                "Or fix the ConfigMap reference in the Pod spec.",
                            ])
                        else:
                            root_cause = f"A referenced ConfigMap does not exist for container {cs.name}."
                            confidence = 0.85
                            recommendations.extend([
                                "Check event messages for the missing ConfigMap name.",
                                "Create the missing ConfigMap.",
                            ])

                elif "secret" in msg_lower:
                    items.append(EvidenceItem(source="event", message=msg))
                    if "not found" in msg_lower or "not exist" in msg_lower:
                        secret_name = self._extract_resource_name(msg, "secret")
                        if secret_name:
                            root_cause = f"Secret '{secret_name}' referenced by container {cs.name} does not exist."
                            confidence = 0.9
                            recommendations.extend([
                                f"Create Secret '{secret_name}' in namespace '{evidence.pod.namespace}'.",
                                "Or fix the Secret reference in the Pod spec.",
                            ])

                elif "serviceaccount" in msg_lower:
                    items.append(EvidenceItem(source="event", message=msg))
                    root_cause = f"ServiceAccount issue for container {cs.name}."
                    recommendations.extend([
                        "Verify the ServiceAccount exists in the namespace.",
                        "Check if the ServiceAccount name is correct.",
                    ])

            if not recommendations:
                # Cross-validate: check Pod spec refs against event messages
                cm_refs = evidence.pod.configmap_refs if evidence.pod else []
                secret_refs = evidence.pod.secret_refs if evidence.pod else []
                if cm_refs:
                    items.append(EvidenceItem(
                        source="pod.spec",
                        message=f"ConfigMap references in spec: {cm_refs}",
                    ))
                if secret_refs:
                    items.append(EvidenceItem(
                        source="pod.spec",
                        message=f"Secret references in spec: {secret_refs}",
                    ))
                recommendations = [
                    "Check the container's volume mounts and environment variable references.",
                    "Verify all referenced ConfigMaps, Secrets, and ServiceAccounts exist.",
                ]
                confidence = 0.6

            findings.append(Finding(
                type="config_error",
                title=f"Container {cs.name} configuration error",
                severity="high",
                confidence=confidence,
                source="rule",
                evidence=items,
                root_cause=root_cause,
                recommendations=recommendations,
            ))

        return findings

    @staticmethod
    def _extract_resource_name(message: str, resource_type: str) -> str | None:
        import re
        pattern = rf"{resource_type}\s+[\"']?([\w.-]+)[\"']?"
        m = re.search(pattern, message, re.IGNORECASE)
        if m:
            return m.group(1)
        return None

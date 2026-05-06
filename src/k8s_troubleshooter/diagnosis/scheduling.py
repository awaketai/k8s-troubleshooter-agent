from __future__ import annotations

from k8s_troubleshooter.diagnosis.base import BaseDiagnoser
from k8s_troubleshooter.diagnosis.finding import EvidenceItem, Finding
from k8s_troubleshooter.diagnosis.registry import register_diagnoser
from k8s_troubleshooter.evidence.model import Evidence


@register_diagnoser("scheduling")
class SchedulingDiagnoser(BaseDiagnoser):
    def can_diagnose(self, evidence: Evidence) -> bool:
        if not evidence.pod:
            return False
        if evidence.pod.phase != "Pending":
            return False
        if evidence.pod.node_name:
            return False
        has_failed_scheduling = any(
            e.reason == "FailedScheduling" for e in evidence.events
        )
        return has_failed_scheduling

    def diagnose(self, evidence: Evidence) -> list[Finding]:
        if not evidence.pod:
            return []

        findings: list[Finding] = []
        items: list[EvidenceItem] = [
            EvidenceItem(
                source="pod_status",
                message=f"Pod is Pending, no node assigned",
            )
        ]

        # Include Pod spec fields in evidence
        pod = evidence.pod
        if pod.resource_requests:
            items.append(EvidenceItem(source="pod.spec", message=f"Resource requests: {pod.resource_requests}"))
        if pod.resource_limits:
            items.append(EvidenceItem(source="pod.spec", message=f"Resource limits: {pod.resource_limits}"))
        if pod.node_selector:
            items.append(EvidenceItem(source="pod.spec", message=f"nodeSelector: {pod.node_selector}"))
        if pod.node_affinity:
            items.append(EvidenceItem(source="pod.spec", message=f"nodeAffinity: {pod.node_affinity}"))
        if pod.tolerations:
            items.append(EvidenceItem(source="pod.spec", message=f"Tolerations: {pod.tolerations}"))
        if pod.pvc_refs:
            items.append(EvidenceItem(source="pod.spec", message=f"PVC refs: {pod.pvc_refs}"))

        scheduling_events = [e for e in evidence.events if e.reason == "FailedScheduling"]
        event_messages = [e.message.lower() for e in scheduling_events if e.message]

        for msg in scheduling_events:
            items.append(EvidenceItem(source="event", message=f"FailedScheduling: {msg.message}"))

        root_cause = "Pod cannot be scheduled."
        recommendations: list[str] = []
        confidence = 0.7

        all_msgs = " ".join(event_messages)

        if "insufficient cpu" in all_msgs:
            root_cause = "Insufficient CPU resources in the cluster."
            confidence = 0.9
            cpu_request = pod.resource_requests.get("cpu", "unknown")
            recommendations.extend([
                f"Reduce CPU request (currently {cpu_request}) or add nodes with more CPU.",
                "Check for other Pods consuming resources on available nodes.",
            ])
        elif "insufficient memory" in all_msgs:
            root_cause = "Insufficient memory resources in the cluster."
            confidence = 0.9
            mem_request = pod.resource_requests.get("memory", "unknown")
            recommendations.extend([
                f"Reduce memory request (currently {mem_request}) or add nodes with more memory.",
            ])
        elif "didn't match" in all_msgs and ("affinity" in all_msgs or "selector" in all_msgs):
            root_cause = "Node affinity/selector conditions cannot be satisfied."
            confidence = 0.88
            if pod.node_selector:
                recommendations.append(f"Current nodeSelector: {pod.node_selector} — verify matching node labels exist.")
            if pod.node_affinity:
                recommendations.append(f"Current nodeAffinity: {pod.node_affinity} — check if any node satisfies these conditions.")
            recommendations.extend([
                "Check nodeSelector and nodeAffinity in the Pod spec.",
                "Verify that nodes with matching labels exist.",
            ])
        elif "taint" in all_msgs and "tolerate" in all_msgs:
            root_cause = "Pod lacks required toleration for available nodes."
            confidence = 0.88
            if pod.tolerations:
                recommendations.append(f"Current tolerations: {pod.tolerations} — may be missing the required one.")
            recommendations.extend([
                "Add appropriate tolerations to the Pod spec.",
                "Check node taints to identify required tolerations.",
            ])
        elif "persistentvolumeclaim" in all_msgs and ("not found" in all_msgs or "unbound" in all_msgs):
            root_cause = "PersistentVolumeClaim is not bound."
            confidence = 0.88
            recommendations.extend([
                "Check PVC status and StorageClass availability.",
                "Verify dynamic provisioning is configured.",
            ])
        elif "unschedulable" in all_msgs:
            root_cause = "No schedulable nodes available (nodes may be cordoned)."
            confidence = 0.8
            recommendations.extend([
                "Check if nodes are cordoned: kubectl get nodes.",
                "Uncordon nodes if appropriate: kubectl uncordon <node>.",
            ])
        else:
            confidence = 0.6
            recommendations.extend([
                "Review FailedScheduling events for details.",
                "Check node resources and Pod requirements.",
            ])

        findings.append(Finding(
            type="scheduling_failed",
            title="Pod scheduling failed",
            severity="high",
            confidence=confidence,
            source="rule",
            evidence=items,
            root_cause=root_cause,
            recommendations=recommendations,
        ))

        return findings

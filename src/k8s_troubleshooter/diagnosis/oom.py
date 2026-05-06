from __future__ import annotations

from k8s_troubleshooter.diagnosis.base import BaseDiagnoser
from k8s_troubleshooter.diagnosis.finding import EvidenceItem, Finding
from k8s_troubleshooter.diagnosis.registry import register_diagnoser
from k8s_troubleshooter.evidence.model import Evidence


@register_diagnoser("oom")
class OOMDiagnoser(BaseDiagnoser):
    def can_diagnose(self, evidence: Evidence) -> bool:
        if not evidence.pod:
            return False
        for cs in evidence.pod.container_statuses + evidence.pod.init_container_statuses:
            if cs.terminated_reason == "OOMKilled" or cs.terminated_exit_code == 137:
                return True
        return False

    def diagnose(self, evidence: Evidence) -> list[Finding]:
        if not evidence.pod:
            return []

        findings: list[Finding] = []
        all_containers = evidence.pod.container_statuses + evidence.pod.init_container_statuses

        for cs in all_containers:
            if cs.terminated_reason != "OOMKilled" and cs.terminated_exit_code != 137:
                continue

            items: list[EvidenceItem] = [
                EvidenceItem(
                    source="container_status",
                    message=f"Container {cs.name} was OOMKilled (exit code {cs.terminated_exit_code}), restarted {cs.restart_count} times",
                )
            ]

            memory_limit = evidence.pod.resource_limits.get("memory", "not set")
            memory_request = evidence.pod.resource_requests.get("memory", "not set")

            items.append(EvidenceItem(
                source="pod.spec",
                message=f"Memory: request={memory_request}, limit={memory_limit}, QoS={evidence.pod.qos_class}",
            ))

            # Check logs for memory-related errors
            mem_errors = []
            for log in evidence.logs:
                if log.container == cs.name:
                    for line in log.lines:
                        ll = line.lower()
                        if any(kw in ll for kw in ("out of memory", "oom", "heap", "memory", "alloc")):
                            mem_errors.append(line)

            if mem_errors:
                items.append(EvidenceItem(
                    source="previous_logs",
                    message=f"Logs contain memory-related errors: {mem_errors[:3]}",
                ))

            confidence = 0.9
            recommendations = []
            qos = evidence.pod.qos_class

            if memory_limit == "not set":
                confidence = 0.85
                recommendations.extend([
                    "No memory limit is set. Set a memory limit to prevent unbounded memory usage.",
                ])
            else:
                recommendations.extend([
                    f"Current memory limit is {memory_limit}. Consider increasing it.",
                ])

            # QoS-specific recommendations
            if qos == "BestEffort":
                confidence = min(confidence, 0.85)
                recommendations.append(
                    "Pod has BestEffort QoS (no requests/limits). Set memory requests and limits for predictable behavior."
                )
            elif qos == "Guaranteed":
                recommendations.append(
                    "Pod has Guaranteed QoS. The memory limit equals the request — the OOM is caused by the application exceeding its configured limit."
                )
            elif qos == "Burstable":
                recommendations.append(
                    "Pod has Burstable QoS. Memory limit is set but may be too tight for the workload."
                )

            recommendations.extend([
                "Check the application for memory leaks.",
                "If using JVM, ensure heap settings are appropriate for the container limit (-Xmx).",
                "If using Node.js, consider --max-old-space-size.",
            ])

            findings.append(Finding(
                type="oom_killed",
                title=f"Container {cs.name} was OOMKilled",
                severity="high",
                confidence=confidence,
                source="rule",
                evidence=items,
                root_cause=f"Container {cs.name} exceeded its memory limit and was killed by the kernel.",
                recommendations=recommendations,
            ))

        return findings

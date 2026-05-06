from __future__ import annotations

from k8s_troubleshooter.diagnosis.base import BaseDiagnoser
from k8s_troubleshooter.diagnosis.finding import EvidenceItem, Finding
from k8s_troubleshooter.diagnosis.registry import register_diagnoser
from k8s_troubleshooter.evidence.model import Evidence


@register_diagnoser("crash_loop")
class CrashLoopDiagnoser(BaseDiagnoser):
    def can_diagnose(self, evidence: Evidence) -> bool:
        if not evidence.pod:
            return False
        for cs in evidence.pod.container_statuses:
            if cs.waiting_reason == "CrashLoopBackOff" and cs.restart_count > 0:
                return True
        for cs in evidence.pod.init_container_statuses:
            if cs.waiting_reason == "CrashLoopBackOff" and cs.restart_count > 0:
                return True
        return False

    def diagnose(self, evidence: Evidence) -> list[Finding]:
        if not evidence.pod:
            return []

        findings: list[Finding] = []
        all_containers = evidence.pod.container_statuses + evidence.pod.init_container_statuses

        for cs in all_containers:
            if cs.waiting_reason != "CrashLoopBackOff" or cs.restart_count == 0:
                continue

            items: list[EvidenceItem] = [
                EvidenceItem(
                    source="container_status",
                    message=f"Container {cs.name} in CrashLoopBackOff, restarted {cs.restart_count} times",
                )
            ]

            if cs.terminated_reason:
                items.append(
                    EvidenceItem(
                        source="container_status",
                        message=f"Last terminated: reason={cs.terminated_reason}, exit_code={cs.terminated_exit_code}",
                    )
                )

            # Check previous logs
            prev_log_errors = []
            for log in evidence.logs:
                if log.container == cs.name and log.lines:
                    for line in log.lines:
                        ll = line.lower()
                        if any(kw in ll for kw in ("error", "fatal", "panic", "exception", "failed")):
                            prev_log_errors.append(line)

            if prev_log_errors:
                items.append(
                    EvidenceItem(
                        source="previous_logs",
                        message=f"Previous logs contain errors: {prev_log_errors[:3]}",
                    )
                )

            # Check probe configuration
            probe_issue = False
            if cs.liveness_probe:
                probe = cs.liveness_probe
                if probe.get("initialDelaySeconds", 0) < 5 and probe.get("failureThreshold", 3) <= 3:
                    probe_issue = True
                    items.append(
                        EvidenceItem(
                            source="probe_config",
                            message=f"Liveness probe may be too aggressive: initialDelaySeconds={probe.get('initialDelaySeconds')}, failureThreshold={probe.get('failureThreshold')}",
                        )
                    )

            # Check ConfigMap/Secret references
            if evidence.pod.configmap_refs:
                items.append(
                    EvidenceItem(
                        source="pod.spec",
                        message=f"ConfigMap refs: {evidence.pod.configmap_refs}",
                    )
                )
            if evidence.pod.secret_refs:
                items.append(
                    EvidenceItem(
                        source="pod.spec",
                        message=f"Secret refs: {evidence.pod.secret_refs}",
                    )
                )

            confidence = 0.8
            root_cause = "Container is crashing repeatedly."
            recommendations = []

            if cs.terminated_exit_code == 1:
                root_cause = f"Container {cs.name} exits with code 1, likely an application startup error."
                confidence = 0.85
                recommendations.extend([
                    "Check container logs for startup errors.",
                    "Verify application configuration and dependencies.",
                ])
            elif cs.terminated_exit_code == 137:
                root_cause = f"Container {cs.name} was killed (exit code 137)."
                confidence = 0.75
                recommendations.extend([
                    "Check if the container is being OOM killed.",
                    "Consider increasing memory limits.",
                ])
            elif cs.terminated_exit_code == 139:
                root_cause = f"Container {cs.name} crashed with segmentation fault (exit code 139)."
                confidence = 0.8
                recommendations.append("This is likely a bug in the application code.")
            elif probe_issue:
                root_cause = f"Liveness probe may be killing container {cs.name} before it's ready."
                confidence = 0.75
                recommendations.extend([
                    "Increase initialDelaySeconds for the liveness probe.",
                    "Consider using a startup probe instead.",
                ])

            if not recommendations:
                recommendations = [
                    "Check container logs for the crash reason.",
                    "Verify application configuration.",
                    "Check if all dependencies are available.",
                ]

            findings.append(Finding(
                type="crash_loop_back_off",
                title=f"Container {cs.name} in CrashLoopBackOff",
                severity="high",
                confidence=confidence,
                source="rule",
                evidence=items,
                root_cause=root_cause,
                recommendations=recommendations,
            ))

        return findings

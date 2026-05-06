from __future__ import annotations

from k8s_troubleshooter.diagnosis.base import BaseDiagnoser
from k8s_troubleshooter.diagnosis.finding import EvidenceItem, Finding
from k8s_troubleshooter.diagnosis.registry import register_diagnoser
from k8s_troubleshooter.evidence.model import Evidence


@register_diagnoser("probe")
class ProbeDiagnoser(BaseDiagnoser):
    def can_diagnose(self, evidence: Evidence) -> bool:
        has_unhealthy_event = any(
            e.reason == "Unhealthy"
            and e.message
            and any(kw in e.message.lower() for kw in ("liveness", "readiness", "startup"))
            for e in evidence.events
        )
        return has_unhealthy_event

    def diagnose(self, evidence: Evidence) -> list[Finding]:
        if not evidence.pod:
            return []

        findings: list[Finding] = []

        unhealthy_events = [
            e for e in evidence.events
            if e.reason == "Unhealthy"
            and e.message
            and any(kw in e.message.lower() for kw in ("liveness", "readiness", "startup"))
        ]

        for event in unhealthy_events:
            msg = event.message or ""
            msg_lower = msg.lower()
            items: list[EvidenceItem] = [
                EvidenceItem(source="event", message=f"Unhealthy: {msg}"),
            ]

            probe_type = "unknown"
            if "liveness" in msg_lower:
                probe_type = "liveness"
            elif "readiness" in msg_lower:
                probe_type = "readiness"
            elif "startup" in msg_lower:
                probe_type = "startup"

            # Find matching container
            matching_container = None
            for cs in evidence.pod.container_statuses:
                probe_config = None
                if probe_type == "liveness" and cs.liveness_probe:
                    probe_config = cs.liveness_probe
                elif probe_type == "readiness" and cs.readiness_probe:
                    probe_config = cs.readiness_probe
                elif probe_type == "startup" and cs.startup_probe:
                    probe_config = cs.startup_probe

                if probe_config:
                    matching_container = cs
                    items.append(EvidenceItem(
                        source="probe_config",
                        message=f"{probe_type} probe: {probe_config}",
                    ))
                    break

            root_cause = f"{probe_type.capitalize()} probe is failing."
            recommendations: list[str] = []
            confidence = 0.75
            mechanism = "unknown"

            if matching_container:
                cs = matching_container
                if cs.restart_count > 0 and probe_type == "liveness":
                    root_cause = f"Liveness probe killing container {cs.name} (restarted {cs.restart_count} times)."
                    confidence = 0.8
                    recommendations.extend([
                        "Increase initialDelaySeconds to give the app more time to start.",
                        "Consider adding a startup probe to gate the liveness probe.",
                        "Increase failureThreshold or periodSeconds.",
                    ])
                elif probe_type == "readiness":
                    root_cause = f"Readiness probe failing for container {cs.name}."
                    confidence = 0.8
                    recommendations.extend([
                        "Check if the application is healthy enough to serve traffic.",
                        "Verify the probe endpoint and port are correct.",
                        "Check if dependencies are available.",
                    ])
                elif probe_type == "startup":
                    root_cause = f"Startup probe failing for container {cs.name}."
                    confidence = 0.8
                    recommendations.extend([
                        "Increase failureThreshold for slow-starting applications.",
                        "Increase initialDelaySeconds.",
                        "Check if the application can start within the probe timeout.",
                    ])
            else:
                recommendations = [
                    f"Check {probe_type} probe configuration.",
                    "Verify the probe endpoint, port, and path.",
                ]

            # Identify and include probe mechanism type in recommendations
            if probe_config:
                mechanism = probe_config.get("type", "unknown")
                mechanism_detail = ""
                if mechanism == "httpGet":
                    mechanism_detail = f"HTTP GET on port {probe_config.get('port', '?')}, path {probe_config.get('path', '/')}"
                elif mechanism == "tcpSocket":
                    mechanism_detail = f"TCP socket on port {probe_config.get('port', '?')}"
                elif mechanism == "exec":
                    mechanism_detail = f"Exec command: {probe_config.get('command', [])}"
                if mechanism_detail:
                    recommendations.insert(0, f"Probe mechanism: {mechanism_detail}")

            # Check logs for context
            for log in evidence.logs:
                for line in log.lines[:5]:
                    ll = line.lower()
                    if "listen" in ll or "bind" in ll or "refused" in ll:
                        items.append(EvidenceItem(
                            source="container_logs",
                            message=f"Container log: {line}",
                        ))
                        break

            findings.append(Finding(
                type=f"probe_failure_{probe_type}",
                title=f"{probe_type.capitalize()} probe failure",
                severity="high" if probe_type == "liveness" else "medium",
                confidence=confidence,
                source="rule",
                evidence=items,
                root_cause=root_cause,
                recommendations=recommendations,
            ))

        return findings

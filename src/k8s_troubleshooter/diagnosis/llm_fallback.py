from __future__ import annotations

import json
import logging

from k8s_troubleshooter.diagnosis.finding import EvidenceItem, Finding
from k8s_troubleshooter.evidence.model import Evidence

logger = logging.getLogger(__name__)


class LLMFallbackDiagnoser:
    def __init__(self, llm_provider=None, policy_guard=None) -> None:
        self._provider = llm_provider
        self._policy_guard = policy_guard

    async def diagnose(
        self, evidence: Evidence, rule_findings: list[Finding]
    ) -> list[Finding]:
        if not self._provider:
            return []

        from k8s_troubleshooter.llm.prompts import LLM_FALLBACK_DIAGNOSIS_PROMPT

        evidence_summary = self._summarize_evidence(evidence)
        rule_summary = self._summarize_findings(rule_findings)

        user_content = f"Evidence:\n{evidence_summary}\n\n"
        if rule_summary:
            user_content += f"Rule-based findings:\n{rule_summary}\n\n"
        user_content += "Please analyze and return findings as JSON array."

        if self._policy_guard:
            user_content = self._policy_guard.check_llm_input(user_content)

        try:
            response = await self._provider.chat(
                messages=[
                    {"role": "system", "content": LLM_FALLBACK_DIAGNOSIS_PROMPT},
                    {"role": "user", "content": user_content},
                ]
            )

            findings = self._parse_response(response)
            return findings
        except Exception as e:
            logger.warning("LLM fallback diagnosis failed: %s", e)
            return []

    def _summarize_evidence(self, evidence: Evidence) -> str:
        parts = []
        if evidence.pod:
            pod = evidence.pod
            parts.append(f"Pod: {pod.namespace}/{pod.name}, phase={pod.phase}")
            for cs in pod.container_statuses:
                parts.append(
                    f"  Container {cs.name}: state={cs.state}, "
                    f"waiting_reason={cs.waiting_reason}, "
                    f"terminated_reason={cs.terminated_reason}, "
                    f"exit_code={cs.terminated_exit_code}, "
                    f"restarts={cs.restart_count}"
                )
        for ev in evidence.events[:10]:
            parts.append(f"Event: reason={ev.reason}, message={ev.message}")
        for log in evidence.logs:
            if log.lines:
                parts.append(f"Logs ({log.container}): {'; '.join(log.lines[:5])}")
        return "\n".join(parts)

    def _summarize_findings(self, findings: list[Finding]) -> str:
        if not findings:
            return ""
        parts = []
        for f in findings:
            parts.append(f"- [{f.severity}] {f.type}: {f.root_cause}")
        return "\n".join(parts)

    def _parse_response(self, response: str) -> list[Finding]:
        try:
            text = response.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1])

            data = json.loads(text)
            if not isinstance(data, list):
                data = [data]

            findings = []
            for item in data:
                evidence_items = []
                for ei in item.get("evidence", []):
                    evidence_items.append(
                        EvidenceItem(
                            source=ei.get("source", "llm"),
                            message=ei.get("message", ""),
                        )
                    )

                findings.append(
                    Finding(
                        type=item.get("type", "llm_analysis"),
                        title=item.get("title", "LLM Analysis"),
                        severity=item.get("severity", "medium"),
                        confidence=min(1.0, max(0.0, item.get("confidence", 0.7))),
                        source="llm",
                        evidence=evidence_items,
                        root_cause=item.get("root_cause", ""),
                        recommendations=item.get("recommendations", []),
                    )
                )
            return findings
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("Failed to parse LLM response: %s", e)
            return []

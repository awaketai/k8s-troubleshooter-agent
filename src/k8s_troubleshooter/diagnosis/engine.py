from __future__ import annotations

from k8s_troubleshooter.diagnosis.base import BaseDiagnoser
from k8s_troubleshooter.diagnosis.finding import Finding
from k8s_troubleshooter.diagnosis.llm_fallback import LLMFallbackDiagnoser
from k8s_troubleshooter.evidence.model import Evidence
from k8s_troubleshooter.harness.schema import DiagnosisRequest

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


class DiagnosisEngine:
    def __init__(
        self,
        diagnosers: list[BaseDiagnoser],
        llm_fallback: LLMFallbackDiagnoser,
    ) -> None:
        self.diagnosers = diagnosers
        self.llm_fallback = llm_fallback

    async def diagnose(
        self, evidence: Evidence, request: DiagnosisRequest
    ) -> list[Finding]:
        rule_findings: list[Finding] = []
        for diagnoser in self.diagnosers:
            if diagnoser.can_diagnose(evidence):
                findings = diagnoser.diagnose(evidence)
                rule_findings.extend(findings)

        llm_findings: list[Finding] = []
        if self._should_use_llm(request, evidence, rule_findings):
            llm_findings = await self.llm_fallback.diagnose(evidence, rule_findings)

        return self._merge_findings(rule_findings, llm_findings)

    def _should_use_llm(
        self,
        request: DiagnosisRequest,
        evidence: Evidence,
        rule_findings: list[Finding],
    ) -> bool:
        if not rule_findings:
            return True
        if any(f.confidence < 0.5 for f in rule_findings):
            return True
        if any(f.needs_llm_analysis for f in rule_findings):
            return True
        if request.depth == "deep":
            return True
        high_severity_count = sum(1 for f in rule_findings if f.severity == "high")
        if high_severity_count > 1:
            return True
        for log in evidence.logs:
            for line in log.lines:
                if "[LOG_UNAVAILABLE]" not in line and any(
                    kw in line.lower()
                    for kw in ("error", "fatal", "panic", "exception")
                ):
                    if not any(
                        line.lower() in " ".join(
                            ei.message.lower() for ei in f.evidence
                        )
                        for f in rule_findings
                    ):
                        return True
        return False

    @staticmethod
    def _merge_findings(
        rule_findings: list[Finding], llm_findings: list[Finding]
    ) -> list[Finding]:
        all_findings = rule_findings + llm_findings
        all_findings.sort(
            key=lambda f: (SEVERITY_ORDER.get(f.severity, 99), -f.confidence)
        )
        return all_findings

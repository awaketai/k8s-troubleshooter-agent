from __future__ import annotations

from k8s_troubleshooter.diagnosis.finding import Finding
from k8s_troubleshooter.evidence.model import ResourceRef
from k8s_troubleshooter.harness.schema import DiagnosisRequest, DiagnosisResult


class SessionContext:
    def __init__(
        self,
        session_id: str = "",
        cluster_context: str = "",
        active_namespace: str = "default",
    ) -> None:
        self.session_id = session_id
        self.cluster_context = cluster_context
        self.active_namespace = active_namespace
        self.last_diagnosed_resources: list[ResourceRef] = []
        self.active_findings: list[Finding] = []
        self.last_diagnosis_results: list[DiagnosisResult] = []

    def update(self, result: DiagnosisResult) -> None:
        self.last_diagnosed_resources.append(result.resource)
        if len(self.last_diagnosed_resources) > 20:
            self.last_diagnosed_resources = self.last_diagnosed_resources[-20:]
        self.active_findings = result.findings
        self.last_diagnosis_results.append(result)
        if len(self.last_diagnosis_results) > 10:
            self.last_diagnosis_results = self.last_diagnosis_results[-10:]


def resolve_context(
    request: DiagnosisRequest, session: SessionContext
) -> DiagnosisRequest:
    updates: dict = {}

    if not request.scope.namespace and session.active_namespace:
        updates.setdefault("scope", {})
        updates["scope"]["namespace"] = session.active_namespace

    if not request.scope.name and request.intent == "diagnose_pod":
        symptoms_lower = [s.lower() for s in request.symptoms]
        for ref in reversed(session.last_diagnosed_resources):
            match = False
            for finding in session.active_findings:
                if any(s in finding.type.lower() for s in symptoms_lower):
                    match = True
                    break
                if any(s in finding.title.lower() for s in symptoms_lower):
                    match = True
                    break
            if match or not symptoms_lower:
                updates.setdefault("scope", {})
                updates["scope"]["name"] = ref.name
                if not request.scope.namespace:
                    updates["scope"]["namespace"] = ref.namespace
                break

    if not request.symptoms and session.active_findings:
        extra_symptoms = [f.type for f in session.active_findings if f.type]
        if extra_symptoms:
            request = request.model_copy(update={"symptoms": extra_symptoms})

    if "scope" in updates:
        request = request.model_copy(update={"scope": request.scope.model_copy(update=updates["scope"])})

    return request

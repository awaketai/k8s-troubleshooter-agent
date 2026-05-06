from __future__ import annotations

from pydantic import BaseModel

from k8s_troubleshooter.evidence.model import ResourceRef


class EvidenceItem(BaseModel):
    source: str
    message: str


class Finding(BaseModel):
    type: str
    title: str
    severity: str = "info"  # critical, high, medium, low, info
    confidence: float = 1.0
    source: str = "rule"  # rule or llm
    evidence: list[EvidenceItem] = []
    root_cause: str = ""
    recommendations: list[str] = []
    related_resources: list[ResourceRef] = []
    needs_llm_analysis: bool = False

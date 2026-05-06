from __future__ import annotations

from abc import ABC, abstractmethod

from k8s_troubleshooter.diagnosis.finding import Finding
from k8s_troubleshooter.evidence.model import Evidence


class BaseDiagnoser(ABC):
    @abstractmethod
    def can_diagnose(self, evidence: Evidence) -> bool: ...

    @abstractmethod
    def diagnose(self, evidence: Evidence) -> list[Finding]: ...

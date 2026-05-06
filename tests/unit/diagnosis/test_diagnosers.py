from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from k8s_troubleshooter.diagnosis.image_pull import ImagePullDiagnoser
from k8s_troubleshooter.diagnosis.oom import OOMDiagnoser
from k8s_troubleshooter.diagnosis.crash_loop import CrashLoopDiagnoser
from k8s_troubleshooter.diagnosis.scheduling import SchedulingDiagnoser
from k8s_troubleshooter.diagnosis.config_error import ConfigErrorDiagnoser
from k8s_troubleshooter.diagnosis.probe import ProbeDiagnoser
from k8s_troubleshooter.evidence.model import Evidence

FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "evidence"


def load_fixture(name: str) -> Evidence:
    path = FIXTURES_DIR / name
    with open(path) as f:
        data = json.load(f)
    return Evidence.model_validate(data)


class TestImagePullDiagnoser:
    def test_can_diagnose_image_pull(self):
        evidence = load_fixture("image-pull-not-found.json")
        d = ImagePullDiagnoser()
        assert d.can_diagnose(evidence) is True

    def test_cannot_diagnose_healthy(self):
        evidence = Evidence(
            resource={"kind": "Pod", "namespace": "default", "name": "ok"},
            pod={"namespace": "default", "name": "ok", "phase": "Running",
                 "container_statuses": [{"name": "main", "ready": True, "state": "running"}]},
        )
        d = ImagePullDiagnoser()
        assert d.can_diagnose(evidence) is False

    def test_image_not_found(self):
        evidence = load_fixture("image-pull-not-found.json")
        d = ImagePullDiagnoser()
        findings = d.diagnose(evidence)
        assert len(findings) == 1
        assert findings[0].type == "image_not_found"
        assert findings[0].confidence >= 0.9

    def test_image_auth_failed(self):
        evidence = load_fixture("image-pull-auth-failed.json")
        d = ImagePullDiagnoser()
        findings = d.diagnose(evidence)
        assert len(findings) == 1
        assert findings[0].type == "image_auth_failed"
        assert findings[0].severity == "high"


class TestOOMDiagnoser:
    def test_can_diagnose_oom(self):
        evidence = load_fixture("oom-killed.json")
        d = OOMDiagnoser()
        assert d.can_diagnose(evidence) is True

    def test_oom_finding(self):
        evidence = load_fixture("oom-killed.json")
        d = OOMDiagnoser()
        findings = d.diagnose(evidence)
        assert len(findings) == 1
        assert findings[0].type == "oom_killed"
        assert findings[0].severity == "high"
        assert any("memory" in r.lower() for r in findings[0].recommendations)


class TestCrashLoopDiagnoser:
    def test_can_diagnose_crash_loop(self):
        evidence = load_fixture("crash-loop-exit-1.json")
        d = CrashLoopDiagnoser()
        assert d.can_diagnose(evidence) is True

    def test_crash_loop_finding(self):
        evidence = load_fixture("crash-loop-exit-1.json")
        d = CrashLoopDiagnoser()
        findings = d.diagnose(evidence)
        assert len(findings) == 1
        assert findings[0].type == "crash_loop_back_off"
        assert findings[0].confidence >= 0.8


class TestSchedulingDiagnoser:
    def test_can_diagnose_pending(self):
        evidence = load_fixture("pending-insufficient-cpu.json")
        d = SchedulingDiagnoser()
        assert d.can_diagnose(evidence) is True

    def test_insufficient_cpu(self):
        evidence = load_fixture("pending-insufficient-cpu.json")
        d = SchedulingDiagnoser()
        findings = d.diagnose(evidence)
        assert len(findings) == 1
        assert findings[0].type == "scheduling_failed"
        assert findings[0].confidence >= 0.9


class TestConfigErrorDiagnoser:
    def test_can_diagnose_config_error(self):
        evidence = load_fixture("configmap-missing.json")
        d = ConfigErrorDiagnoser()
        assert d.can_diagnose(evidence) is True

    def test_configmap_missing(self):
        evidence = load_fixture("configmap-missing.json")
        d = ConfigErrorDiagnoser()
        findings = d.diagnose(evidence)
        assert len(findings) == 1
        assert findings[0].type == "config_error"
        assert "my-config" in findings[0].root_cause


class TestProbeDiagnoser:
    def test_can_diagnose_probe_failure(self):
        evidence = load_fixture("probe-liveness-fail.json")
        d = ProbeDiagnoser()
        assert d.can_diagnose(evidence) is True

    def test_liveness_probe_failure(self):
        evidence = load_fixture("probe-liveness-fail.json")
        d = ProbeDiagnoser()
        findings = d.diagnose(evidence)
        assert len(findings) >= 1
        assert "probe_failure_liveness" == findings[0].type

from __future__ import annotations

from k8s_troubleshooter.diagnosis.registry import load_diagnosers


class TestRegistry:
    def test_load_discovers_all_diagnosers(self):
        diagnosers = load_diagnosers()
        names = {type(d).__name__ for d in diagnosers}
        assert "ImagePullDiagnoser" in names
        assert "OOMDiagnoser" in names
        assert "CrashLoopDiagnoser" in names
        assert "SchedulingDiagnoser" in names
        assert "ConfigErrorDiagnoser" in names
        assert "ProbeDiagnoser" in names

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from k8s_troubleshooter.harness.trace import TraceLogger


class TestTraceLogger:
    def test_start_trace(self):
        logger = TraceLogger()
        logger.start_trace("req-001", "test input", "diagnose_pod")
        trace = logger.get_trace()
        assert trace["request_id"] == "req-001"
        assert trace["user_input"] == "test input"
        assert trace["parsed_intent"] == "diagnose_pod"
        assert trace["tool_calls"] == []

    def test_log_tool_call(self):
        logger = TraceLogger()
        logger.start_trace("req-001", "input", "diagnose_pod")
        logger.log_tool_call(
            tool_name="get_pod",
            arguments={"namespace": "default", "name": "pod-1"},
            status="success",
            duration_ms=50,
        )
        trace = logger.get_trace()
        assert len(trace["tool_calls"]) == 1
        assert trace["tool_calls"][0]["tool"] == "get_pod"
        assert trace["tool_calls"][0]["status"] == "success"

    def test_log_secret_tool_redacts_arguments(self):
        logger = TraceLogger()
        logger.start_trace("req-001", "input", "diagnose_pod")
        logger.log_tool_call(
            tool_name="check_secret_exists",
            arguments={"namespace": "default", "name": "my-secret", "extra": "data"},
            status="success",
            duration_ms=30,
        )
        trace = logger.get_trace()
        logged_args = trace["tool_calls"][0]["arguments"]
        assert logged_args == {"namespace": "default", "name": "my-secret"}

    def test_log_policy_decision(self):
        logger = TraceLogger()
        logger.start_trace("req-001", "input", "diagnose_pod")
        logger.log_policy_decision("get_pod", allowed=False, reason="Write not allowed")
        trace = logger.get_trace()
        assert len(trace["policy_decisions"]) == 1
        assert trace["policy_decisions"][0]["allowed"] is False

    def test_log_diagnosis_result(self):
        logger = TraceLogger()
        logger.start_trace("req-001", "input", "diagnose_pod")
        logger.log_diagnosis_result(findings=["image_not_found"], llm_used=True)
        trace = logger.get_trace()
        assert trace["findings"] == ["image_not_found"]
        assert trace["llm_used"] is True

    def test_flush_writes_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = TraceLogger(log_dir=tmpdir)
            logger.start_trace("req-001", "input", "diagnose_pod")
            logger.log_diagnosis_result(findings=[], llm_used=False)
            logger.flush()

            files = list(Path(tmpdir).glob("*.jsonl"))
            assert len(files) == 1
            with open(files[0]) as f:
                data = json.loads(f.readline())
            assert data["request_id"] == "req-001"

    def test_flush_empty_trace_no_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = TraceLogger(log_dir=tmpdir)
            logger._trace = {}
            logger.flush()
            files = list(Path(tmpdir).glob("*.jsonl"))
            assert len(files) == 0

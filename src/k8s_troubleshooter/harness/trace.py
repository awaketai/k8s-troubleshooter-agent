from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class TraceLogger:
    def __init__(self, log_dir: str = ".traces") -> None:
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(exist_ok=True)
        self._trace: dict[str, Any] = {}

    def start_trace(
        self, request_id: str, user_input: str, parsed_intent: str
    ) -> None:
        self._trace = {
            "request_id": request_id,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "user_input": user_input,
            "parsed_intent": parsed_intent,
            "tool_calls": [],
            "policy_decisions": [],
            "findings": [],
            "llm_used": False,
        }

    def log_tool_call(
        self,
        tool_name: str,
        arguments: dict,
        status: str,
        duration_ms: int,
        result_summary: dict | None = None,
    ) -> None:
        entry: dict[str, Any] = {
            "tool": tool_name,
            "status": status,
            "duration_ms": duration_ms,
        }
        if tool_name == "check_secret_exists":
            ns = arguments.get("namespace", "")
            name = arguments.get("name", "")
            entry["arguments"] = {"namespace": ns, "name": name}
        else:
            entry["arguments"] = arguments

        if result_summary:
            entry["result_summary"] = result_summary

        self._trace.setdefault("tool_calls", []).append(entry)

    def log_policy_decision(
        self, tool_name: str, allowed: bool, reason: str
    ) -> None:
        self._trace.setdefault("policy_decisions", []).append(
            {
                "tool": tool_name,
                "allowed": allowed,
                "reason": reason,
            }
        )

    def log_diagnosis_result(
        self, findings: list[str], llm_used: bool
    ) -> None:
        self._trace["findings"] = findings
        self._trace["llm_used"] = llm_used

    def get_trace(self) -> dict[str, Any]:
        return dict(self._trace)

    def flush(self) -> None:
        if not self._trace:
            return
        request_id = self._trace.get("request_id", "unknown")
        ts = self._trace.get("timestamp", "").replace(":", "-")
        path = self._log_dir / f"{request_id}_{ts}.jsonl"
        with open(path, "a") as f:
            f.write(json.dumps(self._trace, ensure_ascii=False) + "\n")

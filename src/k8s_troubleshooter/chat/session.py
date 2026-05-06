from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

from k8s_troubleshooter.harness.context import SessionContext, resolve_context
from k8s_troubleshooter.harness.executor import ToolExecutor
from k8s_troubleshooter.harness.intent import parse_intent
from k8s_troubleshooter.harness.policy import PolicyGuard
from k8s_troubleshooter.harness.trace import TraceLogger
from k8s_troubleshooter.harness.validator import validate_request
from k8s_troubleshooter.llm.provider import LLMProvider
from k8s_troubleshooter.report.streaming import stream_report
from k8s_troubleshooter.agent.orchestrator import DiagnosisOrchestrator


class ChatSession:
    def __init__(
        self,
        orchestrator: DiagnosisOrchestrator,
        tool_executor: ToolExecutor,
        llm_provider: LLMProvider | None,
        trace_logger: TraceLogger,
        session_context: SessionContext,
        policy_guard: PolicyGuard | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._tool_executor = tool_executor
        self._llm_provider = llm_provider
        self._trace = trace_logger
        self._session = session_context
        self._policy_guard = policy_guard

    @property
    def session_context(self) -> SessionContext:
        return self._session

    async def handle_input(self, user_input: str) -> AsyncIterator[str]:
        request_id = f"diag-{uuid.uuid4().hex[:8]}"

        self._trace.start_trace(
            request_id=request_id,
            user_input=user_input,
            parsed_intent="",
        )

        request = await parse_intent(
            user_input=user_input,
            session=self._session,
            llm_provider=self._llm_provider,
        )

        self._trace._trace["parsed_intent"] = request.intent

        # Explicit context resolve step
        request = resolve_context(request, self._session)

        validation = validate_request(request, self._session)
        if not validation.valid:
            if validation.needs_clarification and validation.clarification_question:
                yield validation.clarification_question + "\n"
            else:
                yield "请求无效，请重新描述你的问题。\n"
            return

        if request.needs_clarification and request.clarification_question:
            yield request.clarification_question + "\n"
            return

        yield "正在诊断...\n\n"

        result = await self._orchestrator.diagnose(request, self._session)

        self._session.update(result)

        llm_used = any(f.source == "llm" for f in result.findings)
        self._trace.log_diagnosis_result(
            findings=[f.type for f in result.findings],
            llm_used=llm_used,
        )
        self._trace.flush()

        async for chunk in stream_report(result, self._llm_provider, self._policy_guard):
            yield chunk

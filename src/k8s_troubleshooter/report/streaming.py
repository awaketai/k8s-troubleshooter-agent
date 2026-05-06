from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from k8s_troubleshooter.harness.schema import DiagnosisResult

logger = logging.getLogger(__name__)
from k8s_troubleshooter.harness.policy import PolicyGuard
from k8s_troubleshooter.llm.provider import LLMProvider
from k8s_troubleshooter.report.formatter import format_text


async def stream_report(
    result: DiagnosisResult,
    llm_provider: LLMProvider | None = None,
    policy_guard: PolicyGuard | None = None,
) -> AsyncIterator[str]:
    header = (
        f"诊断对象: {result.resource.kind}/{result.resource.namespace}/{result.resource.name}\n"
        f"当前状态: {result.status or 'Unknown'}\n"
        f"Trace ID: {result.trace_id}\n\n"
    )
    yield header

    if not result.findings:
        yield "未发现异常。\n"
        return

    rule_findings = [f for f in result.findings if f.source == "rule"]
    llm_findings = [f for f in result.findings if f.source == "llm"]

    if rule_findings:
        yield f"规则引擎诊断结果 ({len(rule_findings)} 个):\n\n"
        for i, finding in enumerate(rule_findings, 1):
            yield (
                f"**{i}. {finding.title}**\n"
                f"   严重性: {finding.severity} | 置信度: {finding.confidence:.0%}\n"
                f"   根因: {finding.root_cause}\n\n"
            )
            if finding.recommendations:
                yield "   建议:\n"
                for rec in finding.recommendations:
                    yield f"   - {rec}\n"
                yield "\n"

    if llm_findings:
        yield f"\n--- 以下为 LLM 推理结论 ({len(llm_findings)} 个) ---\n\n"
        for i, finding in enumerate(llm_findings, 1):
            yield (
                f"**{i}. {finding.title}** (置信度: {finding.confidence:.0%})\n"
                f"   根因: {finding.root_cause}\n\n"
            )
            if finding.recommendations:
                yield "   建议:\n"
                for rec in finding.recommendations:
                    yield f"   - {rec}\n"
                yield "\n"

    if llm_provider and result.findings:
        from k8s_troubleshooter.llm.prompts import REPORT_GENERATION_PROMPT

        text_report = format_text(result)
        if policy_guard:
            text_report = policy_guard.check_llm_input(text_report)
        try:
            yield "\n--- 详细分析报告 ---\n\n"
            async for chunk in llm_provider.chat_stream(
                messages=[
                    {"role": "system", "content": REPORT_GENERATION_PROMPT},
                    {"role": "user", "content": text_report},
                ]
            ):
                yield chunk
            yield "\n"
        except Exception as e:
            logger.warning("LLM report generation failed: %s", e)
            yield "\n[LLM report generation failed]\n"

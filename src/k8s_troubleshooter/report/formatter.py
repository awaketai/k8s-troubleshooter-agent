from __future__ import annotations

from k8s_troubleshooter.harness.schema import DiagnosisResult


def format_json(result: DiagnosisResult) -> str:
    return result.model_dump_json(indent=2)


def format_text(result: DiagnosisResult) -> str:
    lines: list[str] = []

    lines.append(f"诊断对象: {result.resource.kind}/{result.resource.namespace}/{result.resource.name}")
    lines.append(f"当前状态: {result.status or 'Unknown'}")
    lines.append(f"Trace ID: {result.trace_id}")
    lines.append("")

    if not result.findings:
        lines.append("未发现异常。")
        return "\n".join(lines)

    lines.append(f"发现 {len(result.findings)} 个问题:")
    lines.append("")

    for i, finding in enumerate(result.findings, 1):
        source_tag = "[规则引擎]" if finding.source == "rule" else "[LLM推理]"
        lines.append(f"### {i}. {finding.title} {source_tag}")
        lines.append(f"   严重性: {finding.severity} | 置信度: {finding.confidence:.0%}")
        lines.append(f"   根因: {finding.root_cause}")
        lines.append("")
        if finding.recommendations:
            lines.append("   建议:")
            for rec in finding.recommendations:
                lines.append(f"   - {rec}")
            lines.append("")

    return "\n".join(lines)

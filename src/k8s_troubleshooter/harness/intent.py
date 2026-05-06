from __future__ import annotations

import json
import logging
import re

from k8s_troubleshooter.harness.context import SessionContext, resolve_context
from k8s_troubleshooter.harness.schema import DiagnosisRequest, ResourceScope

logger = logging.getLogger(__name__)

_SYMPTOM_MAP = {
    "oom": "OOMKilled",
    "oomkilled": "OOMKilled",
    "imagepull": "ImagePullBackOff",
    "image pull": "ImagePullBackOff",
    "crashloop": "CrashLoopBackOff",
    "crash loop": "CrashLoopBackOff",
    "pending": "Pending",
    "configerror": "CreateContainerConfigError",
    "config error": "CreateContainerConfigError",
    "probe": "ProbeFailure",
    "探针": "ProbeFailure",
    "unhealthy": "ProbeFailure",
}

# Pattern for clearly structured input: ns/name (kubectl-style)
_NS_NAME_PATTERN = re.compile(r"^(\w[\w.-]*)/(\w[\w.-]+)$")


async def parse_intent(
    user_input: str,
    session: SessionContext,
    llm_provider=None,
) -> DiagnosisRequest:
    text = user_input.strip()

    # Fast-path: kubectl-style "ns/name" input — skip LLM entirely
    ns_name_match = _NS_NAME_PATTERN.match(text)
    if ns_name_match:
        request = DiagnosisRequest(
            intent="diagnose_pod",
            scope=ResourceScope(
                kind="Pod",
                namespace=ns_name_match.group(1),
                name=ns_name_match.group(2),
            ),
            symptoms=_detect_symptoms(text),
            depth=_detect_depth(text),
        )
        request = resolve_context(request, session)
        return request

    # LLM-first: use LLM to parse natural language intent
    if llm_provider:
        try:
            llm_request = await _llm_parse_intent(text, session, llm_provider)
            if llm_request is None:
                return _non_k8s_response()
            llm_request = resolve_context(llm_request, session)
            _check_clarification(llm_request)
            return llm_request
        except Exception as e:
            logger.warning("LLM intent parsing failed, falling back to regex: %s", e)

    # Regex fallback (when LLM is unavailable or failed)
    # Detect likely non-K8s input before resolve_context fills in defaults
    scope = _detect_scope(text)
    symptoms = _detect_symptoms(text)
    if (
        not symptoms
        and not scope.name
        and not scope.namespace
        and not any(kw in text.lower() for kw in _DIAGOSE_KEYWORDS)
        and not any(kw in text.lower() for kw in _EXPLAIN_KEYWORDS)
        and "/" not in text
    ):
        return _non_k8s_response()

    request = _regex_parse_intent(text, session)
    return request


def _regex_parse_intent(text: str, session: SessionContext) -> DiagnosisRequest:
    intent = _detect_intent(text)
    scope = _detect_scope(text)
    symptoms = _detect_symptoms(text)
    depth = _detect_depth(text)

    request = DiagnosisRequest(
        intent=intent,
        scope=scope,
        symptoms=symptoms,
        depth=depth,
    )
    request = resolve_context(request, session)
    _check_clarification(request)
    return request


def _non_k8s_response() -> DiagnosisRequest:
    return DiagnosisRequest(
        intent="diagnose_namespace",
        scope=ResourceScope(kind="Namespace", namespace="", name=""),
        needs_clarification=True,
        clarification_question=(
            "我是 Kubernetes 问题诊断助手，可以帮你排查 Pod 故障。\n"
            "例如：\n"
            "  - 排查 default/demo-pod 为什么起不来\n"
            "  - 看看 production namespace 有什么异常的 pod\n"
            "  - 诊断 OOM 的问题\n"
            "输入 /help 查看更多用法。"
        ),
    )


def _check_clarification(request: DiagnosisRequest) -> None:
    if request.intent in ("diagnose_pod", "diagnose_namespace"):
        if not request.scope.namespace and not request.scope.name:
            request.needs_clarification = True
            request.clarification_question = "请提供 namespace 和要排查的资源名称。"
        elif not request.scope.namespace:
            request.needs_clarification = True
            request.clarification_question = "请提供 namespace。"


async def _llm_parse_intent(
    text: str,
    session: SessionContext,
    llm_provider,
) -> DiagnosisRequest | None:
    from k8s_troubleshooter.llm.prompts import INTENT_PARSE_PROMPT

    context_info = f"active_namespace={session.active_namespace}"
    if session.last_diagnosed_resources:
        last = session.last_diagnosed_resources[-1]
        context_info += f", last_resource={last.kind}/{last.namespace}/{last.name}"
    if session.active_findings:
        types = [f.type for f in session.active_findings[:3]]
        context_info += f", active_finding_types={types}"

    messages = [
        {"role": "system", "content": INTENT_PARSE_PROMPT},
        {"role": "user", "content": f"Context: {context_info}\nUser input: {text}"},
    ]

    try:
        response = await llm_provider.chat(messages)
    except Exception:
        return None

    try:
        cleaned = response.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            cleaned = "\n".join(lines[1:-1])
        data = json.loads(cleaned)

        # Check if LLM determined this is not K8s-related
        if data.get("k8s_related") is False:
            return None

        scope_data = data.get("scope") or {}
        kind = scope_data.get("kind") or "Namespace"
        namespace = scope_data.get("namespace")
        name = scope_data.get("name")

        return DiagnosisRequest(
            intent=data.get("intent", "diagnose_namespace"),
            scope=ResourceScope(kind=kind, namespace=namespace, name=name),
            symptoms=data.get("symptoms", []),
            depth=data.get("depth", "normal"),
        )
    except (json.JSONDecodeError, KeyError, Exception) as e:
        logger.debug("Failed to parse LLM intent response: %s", e)
        return None


# --- Regex fallback helpers ---

_DIAGOSE_KEYWORDS = ["排查", "诊断", "查看", "看看", "检查", "扫描", "diagnose", "check", "scan", "look", "show"]
_EXPLAIN_KEYWORDS = ["解释", "为什么", "什么意思", "explain", "why", "what does"]
_QUICK_KEYWORDS = ["快速", "quick"]
_DEEP_KEYWORDS = ["详细", "深入", "deep", "detail"]


def _detect_intent(text: str) -> str:
    text_lower = text.lower()

    if "/" in text and not text.startswith("/"):
        parts = text.split("/")
        if len(parts) >= 2:
            return "diagnose_pod"

    for kw in _EXPLAIN_KEYWORDS:
        if kw in text_lower:
            return "explain_finding"

    if "异常" in text or "unhealthy" in text_lower or "error" in text_lower or "问题" in text:
        if "namespace" in text_lower or "ns" in text_lower.split():
            return "diagnose_namespace"

    for kw in _DIAGOSE_KEYWORDS:
        if kw in text_lower:
            if "namespace" in text_lower or "ns" in text_lower.split():
                return "diagnose_namespace"
            if _extract_pod_name(text):
                return "diagnose_pod"
            return "diagnose_namespace"

    if _extract_pod_name(text):
        return "diagnose_pod"

    return "diagnose_namespace"


def _detect_scope(text: str) -> ResourceScope:
    namespace = _extract_namespace(text)
    name = _extract_pod_name(text)
    kind = "Pod" if name else "Namespace"
    return ResourceScope(kind=kind, namespace=namespace, name=name)


def _extract_namespace(text: str) -> str | None:
    patterns = [
        r"(\w[\w-]*)\s*namespace",
        r"namespace\s*(\w[\w-]*)",
        r"ns\s*(\w[\w-]*)",
        r"(\w[\w-]*)\s*ns\b",
        r"(\w[\w-]*)/",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def _extract_pod_name(text: str) -> str | None:
    patterns = [
        r"(\w[\w.-]+)/(\w[\w.-]+)",
        r"[：:]\s*([a-zA-Z0-9][\w.-]*)\s*$",
        r"pod[/\s]+([a-zA-Z0-9][\w.-]*)",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            if len(m.groups()) == 2:
                return m.group(2)
            name = m.group(1)
            if name.lower() in ("pod", "namespace", "ns", "the"):
                continue
            return name
    return None


def _detect_symptoms(text: str) -> list[str]:
    text_lower = text.lower()
    symptoms = []
    for kw, symptom in _SYMPTOM_MAP.items():
        if kw in text_lower:
            symptoms.append(symptom)
    return list(set(symptoms))


def _detect_depth(text: str) -> str:
    text_lower = text.lower()
    for kw in _QUICK_KEYWORDS:
        if kw in text_lower:
            return "quick"
    for kw in _DEEP_KEYWORDS:
        if kw in text_lower:
            return "deep"
    return "normal"

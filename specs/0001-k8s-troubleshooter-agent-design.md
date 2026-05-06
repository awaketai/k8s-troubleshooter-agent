# K8s Troubleshooter Agent Design

## 背景

Kubernetes 故障排查通常需要同时查看 Pod 状态、事件、日志、Workload 状态、调度信息、资源限制、探针、存储、网络和权限配置。人工排查时，用户需要反复执行 `kubectl describe`、`kubectl logs`、`kubectl get events` 等命令，并结合经验判断根因。

本项目目标是构建一个 Kubernetes 问题排查 agent。agent 通过受控工具收集集群事实，使用规则诊断器识别高频故障，再在必要时调用 LLM 做结构化推理和自然语言报告生成。

本设计采用 **Agent Harness** 架构。Harness 是 agent 的运行控制层，负责理解用户意图、管理上下文、限制工具调用、执行安全策略、记录 trace/audit，并把诊断任务交给下游诊断编排器。LLM 不直接访问 Kubernetes，也不能自由执行 `kubectl`。

## 目标

### Milestone 1: Terminal ChatBot + Harness + Pod 级核心诊断

- 提供终端交互式 ChatBot，支持多轮上下文连续排查。
- 引入 Agent Harness，统一控制意图解析、上下文补全、工具调用、安全策略和审计记录。
- 使用本地 kubeconfig 连接 Kubernetes 集群，第一阶段只支持单集群。
- 支持按 Pod 和 namespace 异常 Pod 扫描进行诊断。
- 覆盖 Pod 常见异常：
  - `ImagePullBackOff`
  - `ErrImagePull`
  - `CrashLoopBackOff`
  - `OOMKilled`
  - `Pending`
  - `CreateContainerConfigError`
  - `CreateContainerError`
  - Probe Failure（`Unhealthy` event）
- 收集 Kubernetes API 中的确定性证据。
- 输出机器可读的结构化诊断结果。
- 输出面向用户的自然语言排查报告，支持 streaming 输出。
- 默认只读，不执行自动修复。
- LLM 后端可插拔，默认支持 OpenAI 兼容接口。

### 后续阶段目标

- 覆盖网络层问题：Service 无法访问、Ingress 配置错误、DNS 解析失败、NetworkPolicy 可能阻断。
- 覆盖存储层问题：PVC Pending、挂载失败、StorageClass 不存在。
- 覆盖 RBAC/权限问题：ServiceAccount 权限不足、API 调用被拒绝。
- 覆盖控制面问题：Deployment rollout 卡住、HPA 不生效、Job/CronJob 失败。
- 覆盖节点层问题：节点 NotReady、磁盘压力、PID 压力、内存压力。
- 支持 API 服务模式、集群内 Agent 部署模式和多集群。
- 支持受控修复，包括 dry-run、人工确认、审计和回滚建议。

### 非目标

- Milestone 1 不做自动修复。
- Milestone 1 不提供 Web UI。
- Milestone 1 不做复杂多 agent 协作。
- Milestone 1 不让 LLM 自主探索整个集群。
- 本项目不替代监控系统。

## 设计原则

### Harness 控制边界

Agent Harness 是所有 agent 行为的入口。用户输入必须先经过 Harness 转换成结构化请求，再由 Harness 调用白名单工具。LLM 可以参与意图解析、长尾推理和报告生成，但不能绕过 Harness 直接访问 Kubernetes。

### 事实优先

Kubernetes 故障排查中的很多判断来自确定性事实，例如 Pod phase、container state、event reason、termination reason、exit code、resource requests/limits、node condition 等。agent 应先通过工具收集和归一化事实，再执行诊断。

### 规则诊断优先，LLM 受控兜底

高频、模式固定的故障由规则诊断器判断。LLM 只在以下场景参与诊断：

- 规则诊断器未命中。
- 规则诊断器命中但置信度低。
- Finding 标记需要 LLM 深入分析。
- 多类异常并存，需要关联推理。
- 用户明确要求深入解释。
- 日志错误无法被规则分类。

LLM 诊断结果必须标注为推理性结论，与规则引擎的确定性结论区分。

### 默认只读

Milestone 1 只做只读诊断。Harness 的 Policy Guard 必须拒绝写操作、拒绝读取 Secret value，并限制日志、事件、资源列表的读取范围。

### 可测试和可审计

每次诊断都应记录请求、解析后的意图、工具调用、策略决策、证据摘要、诊断结果和 LLM 使用情况。诊断器应能基于固定 evidence fixture 做回归测试。

## 总体架构

```text
User
  |
  v
Terminal ChatBot
  |
  v
Agent Harness
  |
  +-- Intent Parser
  +-- Context Resolver
  +-- Request Validator
  +-- Policy Guard
  +-- Tool Registry
  +-- Tool Executor
  +-- Trace / Audit Logger
  |
  v
Diagnosis Orchestrator
  |
  +-- Kubernetes Collectors
  |     +-- Pod Collector
  |     +-- Event Collector
  |     +-- Log Collector
  |     +-- Workload Collector
  |
  +-- Evidence Normalizer
  |
  +-- Diagnosis Engine
  |     +-- Rule-based Diagnosers
  |     +-- LLM Fallback Diagnoser
  |
  +-- Reporter
        +-- JSON Formatter
        +-- Markdown / Streaming Reporter
```

## 工作原理

### 1. 用户输入

用户通过终端 ChatBot 输入自然语言问题：

```text
看看 default namespace 里有什么异常的 pod
```

或：

```text
帮我排查 default/demo-pod 为什么起不来
```

### 2. Harness 解析意图

Intent Parser 先使用规则解析 namespace、resource kind、resource name、状态词和动作词。规则无法确定时，调用 LLM 做结构化解析，但 LLM 只能返回 JSON，不能执行工具。

示例输出：

```json
{
  "intent": "diagnose_namespace",
  "scope": {
    "kind": "Namespace",
    "namespace": "default",
    "name": null
  },
  "filters": {
    "resource_kind": "Pod",
    "status": "unhealthy"
  },
  "mode": "readonly",
  "depth": "normal"
}
```

### 3. Harness 补全上下文

Context Resolver 使用会话上下文补全省略信息。

例如上一轮已发现 `worker-55d8` 是 OOMKilled，用户追问：

```text
详细看看那个 OOM 的
```

Harness 将其解析为：

```json
{
  "intent": "diagnose_pod",
  "scope": {
    "kind": "Pod",
    "namespace": "default",
    "name": "worker-55d8"
  },
  "symptoms": ["OOMKilled"],
  "mode": "readonly",
  "depth": "normal"
}
```

### 4. Harness 校验请求

Request Validator 校验结构化请求：

- 是否存在明确 intent。
- 是否存在必要 scope 字段。
- namespace 是否缺失。
- resource kind 是否受支持。
- mode 是否为允许值。

如果信息不足，Harness 返回澄清问题，而不是立即扫描整个集群。

### 5. Orchestrator 生成工具计划

Orchestrator 接收校验后的 `DiagnosisRequest`，根据 intent 和 scope 生成需要调用的工具列表（tool plan）。Orchestrator 本身不执行工具，而是将 tool plan 交给 Harness 的 Tool Executor。

namespace 异常扫描的典型工具序列：

```text
list_pods(namespace=default)
get_pod(namespace=default, name=<unhealthy-pod>)
get_events(namespace=default, involved_object=<pod>)
get_logs(namespace=default, pod=<pod>, previous=true, tail_lines=200)
get_owner_workload(namespace=default, pod=<pod>)
```

### 6. Harness 执行工具并归一化证据

Harness 的 Tool Executor 逐一执行工具计划中的工具调用。每次调用前经过 Policy Guard 检查，执行后结果经过脱敏和大小限制，并写入 trace。所有 Kubernetes API 调用（包括 Collector 调用）都必须经过 Tool Executor，不可被 Orchestrator 直接绕过，否则 Policy Guard 和 audit trace 将失效。

Tool Executor 将原始结果返回给 Orchestrator，由 Evidence Normalizer 转换为统一 evidence，供诊断器使用。

### 7. 执行诊断

Diagnosis Engine 先运行规则诊断器，再根据策略决定是否调用 LLM Fallback Diagnoser。

规则 Finding 示例：

```json
{
  "type": "image_auth_failed",
  "title": "Image registry authentication failed",
  "severity": "high",
  "confidence": 0.91,
  "source": "rule",
  "root_cause": "Pod image pull failed because registry authentication appears to be missing or invalid."
}
```

### 8. 生成报告

Reporter 输出结构化 JSON 和自然语言报告。自然语言报告需要明确区分规则结论和 LLM 推理结论，并列出关键证据和建议步骤。

### 9. 记录 Trace / Audit

Harness 记录诊断过程：

```json
{
  "request_id": "diag-20260506-001",
  "user_input": "看看 default namespace 里有什么异常的 pod",
  "parsed_intent": "diagnose_namespace",
  "tool_calls": [
    {
      "tool": "list_pods",
      "namespace": "default",
      "status": "success",
      "duration_ms": 120
    }
  ],
  "policy_decisions": [],
  "findings": ["image_auth_failed"],
  "llm_used": false
}
```

## Agent Harness 设计

### Intent Parser

职责：

- 将用户自然语言输入转换为结构化 `DiagnosisRequest`。
- 优先使用规则解析明确字段。
- 规则无法解析时，调用 LLM 进行 JSON 结构化解析。
- 传递给 intent LLM 的上下文必须做最小化：只传当前用户输入、active namespace、资源引用和上一轮 finding 摘要。不得附带 kubeconfig 内容、trace 记录、raw logs、Secret 相关信息或历史完整 evidence。
- 对 LLM 输出进行 schema 校验。
- 缺少必要字段时生成澄清问题。

解析顺序：

```text
keyword / regex parser
  -> context resolver
  -> LLM JSON parser
  -> schema validation
  -> clarification decision
```

需要识别的核心信息：

- intent：`diagnose_pod`（M1）、`diagnose_namespace`（M1）、`explain_finding`（M1）、`diagnose_workload`（M2+，M1 阶段收到时返回不支持提示）。
- resource kind：Pod、Deployment、ReplicaSet、StatefulSet、DaemonSet、Namespace。
- namespace。
- resource name。
- symptoms：`ImagePullBackOff`、`CrashLoopBackOff`、`OOMKilled`、`Pending` 等。
- depth：`quick`、`normal`、`deep`。

### Context Resolver

职责：

- 保存当前 kube context。
- 保存当前 active namespace。
- 保存最近诊断过的资源。
- 保存当前会话中的 active findings。
- 支持用户追问时根据上下文补全目标资源。

会话上下文示例：

```json
{
  "session_id": "session-001",
  "cluster_context": "dev-cluster",
  "active_namespace": "default",
  "last_diagnosed_resources": [
    "Pod/default/demo-pod",
    "Pod/default/worker-55d8"
  ],
  "active_findings": [
    {
      "resource": "Pod/default/worker-55d8",
      "type": "oom_killed",
      "severity": "high"
    }
  ]
}
```

### Request Validator

职责：

- 校验 `DiagnosisRequest` 是否完整。
- 校验 scope 是否与 intent 匹配。
- 校验 mode 是否允许。
- 校验 depth 是否在允许范围内。
- 决定是否需要向用户追问。

示例：

```json
{
  "valid": false,
  "needs_clarification": true,
  "missing_fields": ["namespace", "resource_name"],
  "clarification_question": "请提供要排查的 Pod 名称和 namespace。"
}
```

### Tool Registry

Tool Registry 保存 agent 可调用的白名单工具。每个工具必须定义输入 schema、输出 schema、只读属性、超时、权限要求和脱敏策略。

```python
class ToolSpec(BaseModel):
    name: str
    description: str
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    readonly: bool
    timeout_seconds: int
    required_permissions: list[str]
    redaction_policy: str | None = None
```

Milestone 1 工具：

```text
list_pods
get_pod
get_pod_events
get_container_logs
get_owner_workload
get_pvc_metadata          # Tool Registry 工具，由 Tool Executor 调用 kube client，经过 Policy Guard / trace
check_configmap_exists
check_secret_exists
```

后续工具：

```text
get_service
get_endpoints
get_ingress
get_network_policy
get_node
get_hpa
get_job
check_rbac_permission
```

### Tool Executor

职责：

- 接收 Harness 规划的 `ToolCall`。
- 调用 Policy Guard 做调用前检查。
- 执行工具并设置 timeout。
- 对返回结果做脱敏和大小限制。
- 将结果写入 trace。
- 将工具错误转换为结构化错误。

工具调用结构：

```python
class ToolCall(BaseModel):
    name: str
    arguments: dict
    reason: str
```

工具结果结构：

```python
class ToolResult(BaseModel):
    name: str
    status: Literal["success", "error", "denied"]
    data: dict | None = None
    error: str | None = None
    duration_ms: int
```

### Policy Guard

职责：

- 拒绝写操作。
- 限制可访问 namespace。
- 限制单次诊断最大工具调用次数。
- 限制日志读取行数和字节数。
- 禁止读取 Secret value。
- 禁止把 token、证书、密码、Secret data、完整环境变量值发送给 LLM。
- 对日志和事件 message 做脱敏。
- 对 LLM fallback 的输入做大小限制。

Secret 处理策略：

- `get_secret_value` 不存在于 Tool Registry。
- `check_secret_exists` 只返回 `exists`、`type`、`keys`，不返回 `data`。实现层面：底层调用 K8s API `get secret` 会返回包含 `.data` 值的完整对象，工具实现必须在接收后立即丢弃 `.data` 值，构造安全 DTO（仅含 `exists: bool`、`type: str`、`keys: list[str]`）作为 ToolResult 返回。原始 Secret 对象不得出现在 ToolResult、日志或 LLM 输入中。Trace/audit 对该工具只记录 Secret 资源引用（`namespace/name`），不记录完整 K8s 对象。
- Milestone 1 默认不授予 `secrets list/watch`。
- `check_secret_exists` 作为可选高权限能力，需要用户通过 `--enable-secret-check` 参数或配置文件显式开启。未开启时，Secret 存在性通过 Pod spec 引用名和 event message 推断。

### Trace / Audit Logger

职责：

- 记录用户请求和结构化意图。
- 记录工具调用和耗时。
- 记录被 Policy Guard 拒绝的操作。
- 记录 evidence 摘要。
- 记录诊断结果。
- 记录 LLM 是否被调用、调用目的和 token 用量。

Trace 既用于调试，也用于回归测试和安全审计。

## 核心数据模型

### DiagnosisRequest

```python
class ResourceScope(BaseModel):
    kind: str
    namespace: str | None = None
    name: str | None = None

class DiagnosisRequest(BaseModel):
    intent: Literal[
        "diagnose_pod",         # M1
        "diagnose_namespace",   # M1
        "explain_finding",      # M1
        "diagnose_workload",    # M2+, M1 阶段返回不支持提示
    ]
    scope: ResourceScope
    symptoms: list[str] = []
    filters: dict = {}
    mode: Literal["readonly", "dry_run", "apply"] = "readonly"  # dry_run/apply 为后续阶段预留
    depth: Literal["quick", "normal", "deep"] = "normal"
    needs_clarification: bool = False
    clarification_question: str | None = None
```

Milestone 1 只允许 `mode=readonly`。Request Validator 必须拒绝 `dry_run` 和 `apply`，返回明确错误提示（如 "当前版本仅支持只读模式"）。后续修复阶段实现时再解除限制。

### Evidence

```python
class Evidence(BaseModel):
    resource: ResourceRef
    pod: PodEvidence | None = None
    events: list[EventEvidence] = []
    logs: list[LogEvidence] = []
    workload: WorkloadEvidence | None = None
    related_resources: list[ResourceRef] = []
```

需要抽取的 Pod evidence：

- namespace/name/uid。
- phase。
- conditions。
- init container statuses。
- container statuses。
- waiting reason/message。
- terminated reason/message/exit code。
- restart count。
- image、imageID。
- resource requests/limits。
- nodeName。
- qos class。
- owner references。

### Finding

```python
class Finding(BaseModel):
    type: str
    title: str
    severity: Literal["critical", "high", "medium", "low", "info"]
    confidence: float
    source: Literal["rule", "llm"]
    evidence: list[EvidenceItem]
    root_cause: str
    recommendations: list[str]
    related_resources: list[ResourceRef] = []
    needs_llm_analysis: bool = False
```

### DiagnosisResult

```python
class DiagnosisResult(BaseModel):
    request: DiagnosisRequest
    resource: ResourceRef
    status: str | None
    findings: list[Finding]
    evidence_summary: dict
    trace_id: str
```

## Diagnosis Orchestrator

Diagnosis Orchestrator 接收经过 Harness 校验的 `DiagnosisRequest`，编排诊断流程。

职责：

- 根据 intent 和 scope 生成 tool plan（需要调用哪些工具、参数是什么）。
- 将 tool plan 交给 Harness Tool Executor 执行（Orchestrator 不直接调用 K8s API 或 Collector）。
- 消费 tool results，通过 Evidence Normalizer 构建统一 evidence。
- 调用 Diagnosis Engine。
- 调用 Reporter。
- 将结构化结果返回给 Harness。

Orchestrator 在初始化时调用 `load_diagnosers()` 构建诊断器列表，并传入 `DiagnosisEngine`：

```python
class DiagnosisOrchestrator:
    def __init__(self, kube_client: KubeClient, llm_provider: LLMProvider):
        diagnosers = load_diagnosers()
        llm_fallback = LLMFallbackDiagnoser(llm_provider)
        self.engine = DiagnosisEngine(diagnosers, llm_fallback)
        ...
```

Milestone 1 支持流程：

```text
diagnose_pod
  -> get_pod
  -> get_pod_events
  -> get_container_logs(current/previous)
  -> get_owner_workload
  -> normalize evidence
  -> run diagnosis engine
  -> report

diagnose_namespace (Milestone 1: 逐 Pod 诊断并列出结果)
  -> list_pods
  -> filter unhealthy pods
  -> run diagnose_pod for each unhealthy pod with bounded concurrency
  -> list findings per pod
  -> report

Milestone 2 在此基础上增加跨 Workload 关联分析：按 Deployment/StatefulSet
归并相同根因、生成 namespace 级问题统计和优先级排序。

explain_finding (M1)
  -> 从会话上下文取出指定 finding 及其关联 evidence snapshot
  -> 可选：调用少量工具获取补充上下文（如当前 Pod 状态、最新 events）
  -> 将 finding + evidence 传入 LLM 生成详细解释和建议步骤
  -> 返回解释，不触发新的集群范围扫描或完整诊断流程
```

namespace 诊断必须设置上限：

- 默认最多诊断 10 个异常 Pod。
- 默认每个容器最多读取 200 行日志。
- 默认总工具调用次数不超过 50。
- 超过限制时报告中说明采样范围。

## Kubernetes Collectors

Collectors 负责访问 Kubernetes API 并返回原始事实。Milestone 1 使用本地 kubeconfig：

- 默认读取 `~/.kube/config`。
- 支持 `--kubeconfig` 指定配置文件路径。
- 支持 `--context` 指定 kubeconfig context。
- 用户启动 ChatBot 时选定 context，单个会话内保持不变。

### Pod Collector

- 获取 Pod 对象。
- 获取 Pod owner reference。
- 获取 Pod 关联 PVC、ConfigMap、Secret 引用信息。

### Event Collector

- 获取 namespace 级事件。
- 按 involved object 过滤 Pod 事件。
- 按时间倒序和数量限制返回事件。

### Log Collector

- 获取容器当前日志。
- 获取上一次失败容器日志（previous）。
- 支持 tail lines、since time 和字节数限制。
- 返回前执行脱敏。

### Workload Collector

Milestone 1 只做 Pod owner 关联：

- Pod -> ReplicaSet。
- ReplicaSet -> Deployment。
- Pod -> StatefulSet。
- Pod -> DaemonSet。

后续阶段再扩展 rollout、HPA、Job/CronJob。

## Evidence Normalizer

Normalizer 将 Kubernetes 原始对象转换成诊断器更容易使用的统一 evidence。

职责：

- 抽取 Pod phase、conditions、container states。
- 抽取 waiting/terminated reason 和 message。
- 抽取 restart count、exit code、image、resources。
- 归并 events 并保留 reason、message、count、lastTimestamp。
- 对日志保留摘要、关键错误行和截断标记。
- 移除或脱敏敏感字段。

## Diagnosis Engine

Diagnosis Engine 先运行规则诊断器，再按策略决定是否调用 LLM Fallback Diagnoser。

```python
class DiagnosisEngine:
    def __init__(self, diagnosers: list[BaseDiagnoser], llm_fallback: LLMFallbackDiagnoser):
        self.diagnosers = diagnosers
        self.llm_fallback = llm_fallback

    async def diagnose(self, evidence: Evidence, request: DiagnosisRequest) -> DiagnosisResult:
        rule_findings = []
        for diagnoser in self.diagnosers:
            rule_findings.extend(diagnoser.diagnose(evidence))

        llm_findings = []
        if self._should_use_llm(request, evidence, rule_findings):
            llm_findings = await self.llm_fallback.diagnose(evidence, rule_findings)

        return self._merge_findings(rule_findings, llm_findings)
```

LLM fallback 触发策略：

```text
no rule findings
OR any finding confidence < 0.5        # 使用 any 而非 all：单条低置信度即触发 LLM 补充分析
OR any finding.needs_llm_analysis is true
OR request.depth == "deep"
OR evidence contains unclassified error logs
OR multiple high severity findings coexist
```

### 诊断器注册

Python 装饰器注册只有在模块被 import 后才会生效，因此实现时必须显式加载诊断器模块。

建议使用 `pkgutil.iter_modules` 扫描 `k8s_troubleshooter.diagnosis` 包：

```python
def load_diagnosers() -> list[BaseDiagnoser]:
    import importlib
    import pkgutil
    import k8s_troubleshooter.diagnosis as diagnosis_pkg

    for module in pkgutil.iter_modules(diagnosis_pkg.__path__):
        importlib.import_module(f"{diagnosis_pkg.__name__}.{module.name}")

    return [cls() for cls in get_all_diagnosers().values()]
```

## Milestone 1 诊断场景

### ImagePullBackOff / ErrImagePull

触发条件：

- container state 为 `waiting`。
- waiting reason 为 `ImagePullBackOff` 或 `ErrImagePull`。
- events 中存在 `Failed`、`BackOff`、`FailedToRetrieveImagePullSecret` 等 reason。

检查项：

- 镜像地址和 tag。
- event message 是否包含 `not found`。
- event message 是否包含 `unauthorized`、`authentication required`、`pull access denied`。
- 是否配置 `imagePullSecrets`。
- ServiceAccount 是否配置默认 `imagePullSecrets`。
- event message 是否包含 registry DNS、TLS 或连接超时错误。

常见根因：

- 镜像名或 tag 错误。
- 私有镜像仓库认证失败。
- 缺少 imagePullSecret。
- 节点无法访问镜像仓库。
- registry 证书或 TLS 配置问题。

### CrashLoopBackOff

触发条件：

- container state 为 `waiting`。
- waiting reason 为 `CrashLoopBackOff`。
- restart count 大于 0。

检查项：

- last terminated reason。
- last terminated exit code。
- previous logs。
- 当前 logs。
- liveness/readiness/startup probe 配置。
- ConfigMap/Secret/env 引用。

常见根因：

- 应用启动后立即退出。
- 启动命令或参数错误。
- 配置缺失。
- 依赖服务不可用。
- liveness probe 过早杀死容器。

### OOMKilled

触发条件：

- last terminated reason 为 `OOMKilled`。
- exit code 通常为 `137`。

检查项：

- memory request 和 limit。
- QoS class。
- restart count。
- previous logs 是否存在内存相关错误。

常见根因：

- memory limit 太低。
- 应用内存泄漏。
- JVM、Node.js、Go runtime 未按容器限制配置。
- 突发流量导致内存峰值超过 limit。

### Pending / FailedScheduling

触发条件：

- Pod phase 为 `Pending`。
- Pod 未分配 nodeName。
- events 中存在 `FailedScheduling`。

检查项（M1 不读取 Node 对象，通过 scheduler events 和 Pod spec 推断）：

- scheduler event message（`Insufficient cpu`、`Insufficient memory`、`didn't match Pod's node affinity/selector`、`had taint ... that the pod didn't tolerate` 等）。
- Pod spec 中的 CPU/memory requests。
- Pod spec 中的 nodeSelector。
- Pod spec 中的 node affinity。
- Pod spec 中的 tolerations（与 event message 中报告的 taint 对照）。
- PVC 是否绑定。

常见根因：

- 集群 CPU 或内存不足（从 scheduler event message 推断）。
- nodeSelector/affinity 条件无法满足（从 scheduler event message 推断）。
- 缺少 toleration（从 scheduler event message 中的 taint 信息推断）。
- PVC 未绑定。
- 节点被 cordon（从 scheduler event message 推断；节点真实状态确认需要后续 Node Diagnoser 读取 Node 对象）。

### CreateContainerConfigError / CreateContainerError

触发条件：

- container state 为 `waiting`。
- waiting reason 为 `CreateContainerConfigError` 或 `CreateContainerError`。

检查项：

- 引用的 ConfigMap 是否存在。
- 引用的 Secret 是否存在。
- env key 是否存在。
- volume mount 配置是否引用不存在的 key。
- ServiceAccount 是否存在。

常见根因：

- ConfigMap 或 Secret 缺失。
- ConfigMap/Secret key 名称错误。
- 引用了错误 namespace 中的资源。
- ServiceAccount 缺失。
- volume 或 runtime 配置错误。

### Probe Failure

触发条件：

- events 中出现 `Unhealthy`。
- message 指向 liveness/readiness/startup probe 失败。

检查项：

- probe 类型：HTTP、TCP、exec。
- path、port、command。
- failureThreshold、initialDelaySeconds、periodSeconds、timeoutSeconds。
- 应用实际启动耗时。
- 容器日志中的启动状态。

常见根因：

- 探针路径错误。
- 应用启动慢，liveness probe 过早触发。
- 探针端口错误。
- 依赖服务未就绪导致 readiness 失败。

## 后续诊断场景

### 网络

- Service 无 Endpoints。
- Service selector 与 Pod label 不匹配。
- Ingress backend Service 或 port 配置错误。
- Ingress class 不匹配。
- NetworkPolicy 可能阻断。

NetworkPolicy 诊断第一阶段不做强结论。仅通过静态规则判断“可能阻断”。要确认真实连通性，需要用户提供源、目标、端口，并在后续阶段通过 debug pod 或集群内探测执行主动连通性测试。

### 存储

- PVC Pending。
- StorageClass 不存在。
- PV/PVC accessModes 不匹配。
- FailedMount / FailedAttachVolume。
- RWO volume multi-attach。

### RBAC

- 应用日志出现 Kubernetes API `Forbidden`。
- ServiceAccount 未绑定 Role/ClusterRole。
- Role 缺少目标 resource 或 verb。

### Workload

- Deployment rollout 卡住。
- ReplicaSet 下新 Pod 全部异常。
- HPA metrics 不可用。
- Job/CronJob 失败。

### Node

- Node NotReady。
- MemoryPressure、DiskPressure、PIDPressure。
- 节点 allocatable 与 Pod requests 分析。

实时 CPU/内存使用不来自 Kubernetes core API。后续如需实时使用量，需要接入 metrics-server 的 `metrics.k8s.io` 或 Prometheus。

## LLM Provider

LLM Provider 采用可插拔设计，默认支持 OpenAI 兼容 API。

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator


class LLMProvider(ABC):
    @abstractmethod
    async def chat(self, messages: list[dict], **kwargs) -> str:
        ...

    @abstractmethod
    async def chat_stream(self, messages: list[dict], **kwargs) -> AsyncIterator[str]:
        ...
```

配置示例：

```yaml
llm:
  provider: openai
  api_key_env: OPENAI_API_KEY
  base_url: https://api.openai.com/v1
  model_env: OPENAI_MODEL
```

不在设计文档中硬编码默认模型名。模型由配置或环境变量显式指定。

LLM 输入约束：

- 只传递脱敏后的 evidence。
- 不传递 Secret value、token、证书、完整环境变量值。
- 日志必须截断和摘要。
- LLM 输出的命令是建议，不自动执行。

## 输出格式

### 结构化结果

```json
{
  "trace_id": "diag-20260506-001",
  "request": {
    "intent": "diagnose_pod",
    "scope": {
      "kind": "Pod",
      "namespace": "default",
      "name": "demo-pod"
    },
    "mode": "readonly",
    "depth": "normal"
  },
  "resource": {
    "kind": "Pod",
    "namespace": "default",
    "name": "demo-pod"
  },
  "status": "ImagePullBackOff",
  "findings": [
    {
      "type": "image_auth_failed",
      "title": "Image registry authentication failed",
      "severity": "high",
      "confidence": 0.91,
      "source": "rule",
      "evidence": [
        {
          "source": "event",
          "message": "pull access denied"
        },
        {
          "source": "pod.spec",
          "message": "imagePullSecrets is not configured"
        }
      ],
      "root_cause": "The image appears to be hosted in a private registry, but the Pod does not have valid pull credentials.",
      "recommendations": [
        "Create a docker-registry Secret in the same namespace.",
        "Attach the Secret through pod.spec.imagePullSecrets or the ServiceAccount.",
        "Retry the rollout after confirming registry permissions."
      ]
    }
  ]
}
```

### 自然语言报告

报告应包含：

- 诊断对象。
- 当前状态。
- 最可能根因。
- 关键证据。
- 建议修复步骤。
- 可选排查命令。
- 置信度和不确定性说明。
- 明确区分规则引擎结论和 LLM 推理结论。

示例：

```text
Pod default/demo-pod 当前处于 ImagePullBackOff。

最可能原因是镜像仓库认证失败（置信度 91%，规则引擎诊断）。关键证据是事件中出现 pull access denied，同时 Pod 模板没有配置 imagePullSecrets。

建议创建 docker-registry 类型 Secret，并配置到 Pod 模板或 ServiceAccount。修复后重新触发 Deployment rollout。
```

## 权限模型

### 本地 CLI 模式

Milestone 1 使用用户本地 kubeconfig。agent 不创建集群内 ServiceAccount，也不要求安装 ClusterRole。

用户当前 kubeconfig identity 需要具备以下只读能力：

- `pods`: `get`, `list`
- `pods/log`: `get`
- `events`: `get`, `list`
- `replicasets`, `deployments`, `statefulsets`, `daemonsets`: `get`, `list`
- `persistentvolumeclaims`: `get`, `list`
- `configmaps`: `get`
- `serviceaccounts`: `get`（检查 SA 默认 imagePullSecrets）

Secret 默认不读取。若启用 Secret 存在性检查，需要用户显式开启高权限选项，并只允许 `get` 指定 Secret，不允许 `list/watch`。

### 集群内 Agent 模式

后续部署到集群内时，提供只读 RBAC。基础权限示例：

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: k8s-troubleshooter-readonly
rules:
  - apiGroups: [""]
    resources:
      - pods
      - pods/log
      - events
      - services
      - endpoints
      - persistentvolumeclaims
      - configmaps
      - serviceaccounts
    verbs: ["get", "list", "watch"]
  - apiGroups: ["apps"]
    resources:
      - deployments
      - replicasets
      - statefulsets
      - daemonsets
    verbs: ["get", "list", "watch"]
```

扩展诊断按需增加 RBAC：

- 网络诊断：`ingresses`, `networkpolicies`。
- 存储诊断：`persistentvolumes`, `storageclasses`。
- Workload 诊断：`jobs`, `cronjobs`, `horizontalpodautoscalers`。
- RBAC 诊断：`roles`, `clusterroles`, `rolebindings`, `clusterrolebindings`。
- Node 诊断：`nodes`。

> 注：基础 ClusterRole 不含 `nodes`。M1 Pod Pending 场景通过 scheduler Event messages（`Insufficient cpu` 等）推断节点资源不足，不需要直接读取 Node 对象。

Secret 权限不放入基础 ClusterRole。若用户明确启用，单独提供可选 Role，并在安全说明中标注风险。

## 部署形态

### Terminal ChatBot 模式

Milestone 1 交付形态。

```bash
k8s-troubleshooter --context dev-cluster
```

示例交互：

```text
Connected to cluster: dev-cluster
> default namespace 有什么异常的 pod？

正在扫描 default namespace 中的 Pod...

发现 2 个异常 Pod：
1. demo-pod: ImagePullBackOff
2. worker-pod: OOMKilled (已重启 5 次)

> 详细看看 worker-pod

正在收集 worker-pod 的诊断信息...
```

启动参数：

```text
k8s-troubleshooter [options]
  --kubeconfig PATH
  --context NAME
  --config PATH
  --namespace NAME
  --max-tool-calls N
  --log-tail-lines N
  --enable-secret-check    启用 Secret 元数据检查（需要 secrets get 权限）
```

### API 服务模式

后续阶段提供，用于集成 Web UI、Chat UI 或外部系统。

```http
POST /diagnose
Content-Type: application/json

{
  "intent": "diagnose_pod",
  "scope": {
    "kind": "Pod",
    "namespace": "default",
    "name": "demo-pod"
  }
}
```

### 集群内 Agent 模式

后续阶段提供，用于长期运行和主动诊断：

- watch Pod 和 Event。
- 自动识别异常。
- 生成诊断报告。
- 集成 Slack、飞书、Webhook、告警系统。

## 安全与审计

- 默认只读。
- Harness 拒绝所有写操作。
- 不把 Secret value、token、证书、完整环境变量值发送给 LLM。
- 日志进入 LLM 前必须脱敏和截断。
- 所有工具调用记录 trace。
- 所有策略拒绝记录 audit。
- LLM 输出的命令只作为建议，不自动执行。
- 后续自动修复必须包含 dry-run、用户确认、变更预览、审计日志和回滚建议。

## 测试策略

### Harness 单元测试

- Intent Parser 能解析明确 Pod、namespace 和症状。
- Context Resolver 能根据上一轮 finding 补全目标资源。
- Request Validator 能发现缺失字段并生成澄清问题。
- Policy Guard 能拒绝写操作、Secret value 读取和超限日志读取。
- Tool Executor 能记录成功、失败、超时和拒绝。

### 诊断器单元测试

每个诊断器使用固定 evidence fixture 测试。

覆盖场景：

- 镜像不存在。
- 镜像认证失败。
- 容器 OOMKilled。
- Pod Pending 且 CPU 不足。
- ConfigMap 缺失。
- liveness probe 失败。
- CrashLoopBackOff 且 previous logs 存在异常。

### 集成测试

使用 kind 或 envtest 构造真实 Kubernetes 对象。

覆盖：

- Collector 能正确读取 Pod、Event、Log 和 Workload。
- Normalizer 能从 Kubernetes 对象中抽取统一 evidence。
- Orchestrator 能返回完整报告。
- LLM Provider 接口调用正确。
- ChatBot 多轮上下文传递正确。

### 回归测试

为每个已知故障样本保存输入 evidence 和期望 finding：

```text
tests/fixtures/evidence/image-pull-auth-failed.json
tests/fixtures/evidence/oom-killed.json
tests/fixtures/evidence/pending-insufficient-cpu.json
tests/fixtures/evidence/configmap-missing.json
```

回归测试应验证：

- finding type。
- severity。
- confidence 范围。
- 关键 evidence。
- recommendation 是否包含必要动作。

## 里程碑

### Milestone 1: Harness + Terminal ChatBot + Pod 诊断

- 初始化 Python 项目，使用 `uv` 管理依赖。
- 实现配置加载。
- 实现 kubeconfig 加载和集群连接。
- 实现 Terminal ChatBot。
- 实现 Harness：
  - Intent Parser。
  - Context Resolver。
  - Request Validator。
  - Policy Guard。
  - Tool Registry。
  - Tool Executor。
  - Trace / Audit Logger。
- 实现 LLM Provider 可插拔接口。
- 实现 Pod、Event、Log、Workload collector。
- 实现 Evidence Normalizer。
- 实现诊断器注册机制。
- 实现 ImagePull、CrashLoop、OOM、Pending、ConfigError、Probe 诊断器。
- 实现 LLM Fallback 诊断。
- 实现 Reporter，支持 JSON 和 streaming Markdown。
- 增加 Harness、诊断器和 collector 测试。

### Milestone 2: 跨资源关联诊断和扩展

- 增加 namespace 级跨 Workload 关联分析（例如多个 Deployment 下的 Pod 出现相同根因时归并报告、按 Workload 维度聚合 finding 统计）。
- 实现 Storage Collector 和 Storage Diagnoser。
- 实现基础 Workload Diagnoser（Deployment rollout、HPA、Job/CronJob）。
- 增加日志脱敏和摘要能力。
- 增加更多 evidence fixture。

### Milestone 3: 网络、RBAC、Node 诊断

- 实现 Network Collector 和 Network Diagnoser。
- 实现 RBAC Collector 和 RBAC Diagnoser。
- 实现 Node Collector 和 Node Diagnoser。
- 可选接入 metrics-server 或 Prometheus。

### Milestone 4: API 服务和集群内部署

- 提供 HTTP API。
- 提供 Kubernetes manifest 或 Helm chart。
- 使用 ServiceAccount 和只读 RBAC。
- 支持主动 watch 异常事件。

### Milestone 5: 受控修复

- 增加 dry-run 修复建议。
- 支持用户确认后执行有限 patch。
- 增加审计日志。
- 增加回滚建议。

## 技术栈

- 语言：Python 3.11+
- 包管理：uv
- K8s 客户端：kubernetes 官方 Python 客户端
- LLM SDK：openai AsyncOpenAI，兼容 OpenAI API 格式后端
- 终端交互：prompt_toolkit + rich
- 配置管理：pydantic + YAML
- 异步框架：asyncio
- 测试：pytest + pytest-asyncio

## 建议目录结构

```text
.
├── src/
│   └── k8s_troubleshooter/
│       ├── __init__.py
│       ├── main.py
│       ├── cli.py
│       ├── config.py
│       ├── harness/
│       │   ├── __init__.py
│       │   ├── intent.py
│       │   ├── context.py
│       │   ├── schema.py
│       │   ├── validator.py
│       │   ├── policy.py
│       │   ├── tools.py
│       │   ├── executor.py
│       │   └── trace.py
│       ├── chat/
│       │   ├── __init__.py
│       │   ├── session.py
│       │   └── terminal.py
│       ├── agent/
│       │   ├── __init__.py
│       │   └── orchestrator.py
│       ├── kube/
│       │   ├── __init__.py
│       │   ├── client.py
│       │   ├── pod_collector.py
│       │   ├── event_collector.py
│       │   ├── log_collector.py
│       │   └── workload_collector.py
│       ├── evidence/
│       │   ├── __init__.py
│       │   ├── model.py
│       │   └── normalizer.py
│       ├── diagnosis/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   ├── registry.py
│       │   ├── engine.py
│       │   ├── finding.py
│       │   ├── image_pull.py
│       │   ├── crash_loop.py
│       │   ├── oom.py
│       │   ├── scheduling.py
│       │   ├── config_error.py
│       │   ├── probe.py
│       │   └── llm_fallback.py
│       ├── llm/
│       │   ├── __init__.py
│       │   ├── provider.py
│       │   ├── openai_provider.py
│       │   └── prompts.py
│       └── report/
│           ├── __init__.py
│           ├── formatter.py
│           └── streaming.py
├── tests/
│   ├── unit/
│   │   ├── harness/
│   │   ├── diagnosis/
│   │   ├── evidence/
│   │   └── llm/
│   ├── integration/
│   └── fixtures/
│       └── evidence/
├── config.example.yaml
├── pyproject.toml
├── specs/
│   └── 0001-k8s-troubleshooter-agent-design.md
└── README.md
```

## 后续决策点

- 是否需要持久化会话上下文。
- 是否需要支持多集群和跨集群聚合诊断。
- 是否需要接入 Prometheus、Loki、OpenTelemetry 或 Alertmanager。
- 是否需要支持用户自定义诊断器。
- 自动修复的权限边界和审批流程。

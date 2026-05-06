# K8s Troubleshooter Agent — Milestone 1 实现计划

本文档基于 `specs/0001-k8s-troubleshooter-agent-design.md` 的设计，将 Milestone 1 拆解为可执行的实现步骤。

## 实现范围

Milestone 1 交付：Terminal ChatBot + Agent Harness + Pod 级核心诊断。

交付能力：

- 终端交互式 ChatBot，多轮上下文连续排查。
- Agent Harness 控制意图解析、工具调用、安全策略和审计。
- 按 Pod 和 namespace 异常 Pod 扫描诊断。
- 覆盖 ImagePullBackOff、CrashLoopBackOff、OOMKilled、Pending、CreateContainerConfigError/Error、Probe Failure。
- 结构化 JSON + streaming 自然语言报告。
- LLM 后端可插拔，默认 OpenAI 兼容。
- 默认只读，不做自动修复。

## 工程原则

实现过程中遵循以下原则：

### SOLID

- **Single Responsibility**：每个类只做一件事。`PolicyGuard` 只做策略检查，不做工具执行；`EvidenceNormalizer` 只做数据转换，不做诊断。诊断器每个文件一个，只处理一种故障模式。
- **Open/Closed**：诊断器通过装饰器注册 + `pkgutil` 自动发现，新增诊断器不需要修改 Engine 或 Orchestrator 代码。LLM Provider 通过 ABC 扩展，新增后端不改已有代码。
- **Liskov Substitution**：所有 `BaseDiagnoser` 子类行为一致——`can_diagnose` 返回 bool，`diagnose` 返回 `list[Finding]`。所有 `LLMProvider` 子类都满足 `chat` / `chat_stream` 契约。
- **Interface Segregation**：Collector 不暴露完整 kubernetes client，只暴露具体方法（`get_pod`、`get_events`）。Tool handler 只接收 `arguments: dict`，返回 `dict`，不感知 Harness 内部。
- **Dependency Inversion**：Orchestrator 依赖 `ToolExecutor` 接口而非具体 Collector；DiagnosisEngine 依赖 `BaseDiagnoser` 抽象而非具体诊断器；ChatSession 依赖 `LLMProvider` ABC 而非 `OpenAIProvider`。

### DRY

- Evidence 数据模型定义一次，Collectors、Normalizer、Diagnosers、Reporter 共用。
- 工具调用的 Policy 检查、timeout、脱敏、trace 写入统一在 `ToolExecutor` 中处理，各 tool handler 不重复实现。
- Finding 构造使用统一的 `Finding` model，诊断器只填充字段值。
- Prompt 模板集中在 `llm/prompts.py`，不散落在各模块。

### KISS

- M1 不做过度抽象：不需要插件系统框架，`pkgutil` + 装饰器够用。
- 不引入 ORM 或消息队列，Trace 直接写 JSON Lines 文件。
- 不做异步 Collector 并发调度框架，tool plan 顺序执行（M1 工具调用次数有限，顺序执行延迟可接受）。
- 配置用 Pydantic + YAML，不造配置框架。
- Intent Parser 先写死规则覆盖常见表达，只在规则失败时才调 LLM，不一上来就全量走 LLM。

### YAGNI

- 不实现 M1 不需要的功能：不写 `dry_run`/`apply` 执行逻辑，Validator 直接拒绝即可；不实现 Network/Storage/RBAC/Node Diagnoser 的骨架代码。
- 不预留 "可能用到" 的抽象层：不为多集群写 cluster router；不为 Web UI 预留 HTTP handler；不为插件市场写 plugin loader。
- Tool Registry 只注册 M1 用到的 8 个工具，后续工具在对应 Milestone 实现时再加。
- 配置项只暴露 M1 需要的参数，不提前加 `max_concurrent_diagnoses`、`cache_ttl` 等后续才有意义的选项。
- 不写用不到的 util/helper。如果只有一个地方用，就内联；重复出现第二次时再提取。

### 其他

- **Fail Fast**：启动时验证集群连接、LLM 配置、权限，不等到用户提问时才报错。
- **Explicit over Implicit**：所有工具必须在 Tool Registry 显式注册；LLM findings 必须标注 `source: "llm"`；mode 限制在 Validator 显式拒绝。
- **Testable by Design**：所有核心逻辑接收接口而非具体实现，可 mock 测试。Diagnosers 纯函数式——输入 Evidence，输出 Findings，无外部依赖。

## 实现阶段

共 8 个阶段，按依赖关系排序。每个阶段结束时应有可运行的测试验证交付物。

---

## Phase 1: 项目骨架和配置

**目标**：初始化项目结构，配置加载，能 `uv run k8s-troubleshooter --help`。

### 1.1 初始化项目

```text
操作：
- uv init，创建 pyproject.toml
- 配置 Python 3.11+ 要求
- 添加依赖：kubernetes, openai, prompt-toolkit, rich, pydantic, pyyaml, pytest, pytest-asyncio
- 创建 src/k8s_troubleshooter/ 包结构（参照设计文档目录结构）
- 创建 cli.py 入口（argparse 或 click）
```

文件清单：

```text
pyproject.toml
src/k8s_troubleshooter/__init__.py
src/k8s_troubleshooter/main.py
src/k8s_troubleshooter/cli.py
```

### 1.2 配置加载

```text
文件：src/k8s_troubleshooter/config.py
```

实现：

- 定义 `AppConfig` Pydantic model，包含：
  - `kubeconfig: str | None`（默认 `~/.kube/config`）
  - `context: str | None`
  - `namespace: str | None`
  - `llm: LLMConfig`（provider, api_key_env, base_url, model_env）
  - `max_tool_calls: int = 50`
  - `log_tail_lines: int = 200`
  - `max_pods_per_scan: int = 10`
  - `enable_secret_check: bool = False`
- 支持从 YAML 文件加载（`--config PATH`）。
- 支持 CLI 参数覆盖配置文件值。
- 创建 `config.example.yaml`。

### 1.3 CLI 入口

```text
文件：src/k8s_troubleshooter/cli.py
```

实现：

- 解析命令行参数：`--kubeconfig`、`--context`、`--config`、`--namespace`、`--max-tool-calls`、`--log-tail-lines`、`--enable-secret-check`。
- 加载配置并创建 `AppConfig`。
- 调用 `main.py` 中的 `async def run(config: AppConfig)` 启动应用。

### 1.4 测试

```text
tests/unit/test_config.py
```

- 从 YAML 加载配置。
- CLI 参数覆盖 YAML。
- 缺少必填字段时抛出 ValidationError。
- `enable_secret_check` 默认 False。

**阶段交付**：`uv run k8s-troubleshooter --help` 正常输出，配置加载通过测试。

---

## Phase 2: Kubernetes 连接和 Collectors

**目标**：能连接集群并读取 Pod、Event、Log、Workload 原始对象。

### 2.1 Kube Client

```text
文件：src/k8s_troubleshooter/kube/client.py
```

实现：

- `KubeClient` 类，封装 kubernetes Python 客户端初始化。
- 根据 `AppConfig` 加载 kubeconfig 和 context。
- 提供 `CoreV1Api` 和 `AppsV1Api` accessor。
- 连接验证：启动时调用 `list_namespaces` 验证连通性，失败时给出明确错误。
- 异步适配：kubernetes Python 客户端是同步的，使用 `asyncio.to_thread` 包装。

### 2.2 Pod Collector

```text
文件：src/k8s_troubleshooter/kube/pod_collector.py
```

实现：

- `list_pods(namespace: str) -> list[V1Pod]`
- `get_pod(namespace: str, name: str) -> V1Pod`
- 从 Pod spec 提取 PVC、ConfigMap、Secret 引用列表。
- 提取 owner references。

### 2.3 Event Collector

```text
文件：src/k8s_troubleshooter/kube/event_collector.py
```

实现：

- `get_events(namespace: str, involved_object_name: str | None, involved_object_kind: str | None) -> list[V1Event]`
- 按 `lastTimestamp` 倒序排序。
- 支持数量限制（默认最近 50 条）。

### 2.4 Log Collector

```text
文件：src/k8s_troubleshooter/kube/log_collector.py
```

实现：

- `get_logs(namespace: str, pod: str, container: str, previous: bool = False, tail_lines: int = 200) -> str`
- 字节数限制（默认 512KB）。
- 容器不存在或日志不可用时返回结构化错误，不抛异常。

### 2.5 Workload Collector

```text
文件：src/k8s_troubleshooter/kube/workload_collector.py
```

实现（M1 只做 owner 关联）：

- `get_owner_workload(namespace: str, owner_references: list) -> dict | None`
- 支持链路：Pod → ReplicaSet → Deployment、Pod → StatefulSet、Pod → DaemonSet。

### 2.6 测试

```text
tests/unit/kube/test_pod_collector.py
tests/unit/kube/test_event_collector.py
tests/unit/kube/test_log_collector.py
tests/unit/kube/test_workload_collector.py
```

- 使用 mock kubernetes client 测试各 collector 的返回结构。
- 测试异常情况：Pod 不存在、日志不可用、owner chain 断裂。

**阶段交付**：Collectors 能通过 mock 测试；可选用 kind 集群做手动验收。

---

## Phase 3: 数据模型和 Evidence Normalizer

**目标**：定义核心数据模型，实现 Kubernetes 原始对象到统一 Evidence 的转换。

### 3.1 核心数据模型

```text
文件：src/k8s_troubleshooter/evidence/model.py
文件：src/k8s_troubleshooter/diagnosis/finding.py
文件：src/k8s_troubleshooter/harness/schema.py
```

实现（均为 Pydantic BaseModel）：

**evidence/model.py**：
- `ResourceRef(kind, namespace, name, uid)`
- `PodEvidence(namespace, name, uid, phase, conditions, init_container_statuses, container_statuses, qos_class, node_name, owner_references, resource_requests, resource_limits, ...)`
- `ContainerStatusEvidence(name, ready, state, waiting_reason, waiting_message, terminated_reason, terminated_message, terminated_exit_code, restart_count, image, image_id)`
- `EventEvidence(reason, message, count, last_timestamp, type, source_component)`
- `LogEvidence(container, lines, truncated, redacted)`
- `WorkloadEvidence(kind, name, replicas, ready_replicas, conditions)`
- `Evidence(resource, pod, events, logs, workload, related_resources)`

**diagnosis/finding.py**：
- `EvidenceItem(source, message)`
- `Finding(type, title, severity, confidence, source, evidence, root_cause, recommendations, related_resources, needs_llm_analysis)`

**harness/schema.py**：
- `ResourceScope(kind, namespace, name)`
- `DiagnosisRequest(intent, scope, symptoms, filters, mode, depth, needs_clarification, clarification_question)`
- `DiagnosisResult(request, resource, status, findings, evidence_summary, trace_id)`
- `ToolCall(name, arguments, reason)`
- `ToolResult(name, status, data, error, duration_ms)`
- `ToolSpec(name, description, input_schema, output_schema, readonly, timeout_seconds, required_permissions, redaction_policy)`

### 3.2 Evidence Normalizer

```text
文件：src/k8s_troubleshooter/evidence/normalizer.py
```

实现：

- `normalize_pod(pod: V1Pod) -> PodEvidence`：抽取 phase、conditions、container states、waiting/terminated reason、restart count、exit code、image、resources、nodeName、qos、owner references。
- `normalize_events(events: list[V1Event]) -> list[EventEvidence]`：抽取 reason、message、count、lastTimestamp。
- `normalize_logs(raw_logs: str, container: str) -> LogEvidence`：保留关键错误行、截断标记。
- `normalize_workload(workload_obj) -> WorkloadEvidence`。
- `build_evidence(pod, events, logs, workload) -> Evidence`：组合以上结果。
- 脱敏：移除 env value 中可能的敏感信息、移除 annotation 中的 token。

### 3.3 测试

```text
tests/unit/evidence/test_model.py
tests/unit/evidence/test_normalizer.py
tests/fixtures/evidence/  (创建基础 fixture)
```

- 从 fixture JSON 构建 Evidence。
- Normalizer 能正确抽取 OOMKilled、ImagePullBackOff、Pending 等状态。
- 脱敏逻辑测试。

**阶段交付**：数据模型定义完整，Normalizer 通过 fixture 测试。

---

## Phase 4: Agent Harness

**目标**：实现 Harness 核心组件：Intent Parser、Context Resolver、Request Validator、Policy Guard、Tool Registry、Tool Executor、Trace Logger。

### 4.1 Intent Parser

```text
文件：src/k8s_troubleshooter/harness/intent.py
```

实现：

- `parse_intent(user_input: str, session_context: SessionContext, llm_provider: LLMProvider | None) -> DiagnosisRequest`
- 规则解析层：
  - 正则匹配 namespace（`(\w+)\s*namespace`、`namespace\s*(\w+)`）。
  - 正则匹配 Pod 名称（`pod[/\s](\S+)`、资源路径 `namespace/pod-name`）。
  - 关键词匹配 symptoms（`OOM`、`ImagePull`、`CrashLoop`、`Pending`、`探针`、`probe` 等）。
  - 关键词匹配 intent（`排查`/`诊断`/`查看`/`看看` → diagnose；`解释`/`为什么`/`什么意思` → explain_finding）。
  - 关键词匹配 depth（`快速`/`quick` → quick；`详细`/`深入`/`deep` → deep）。
- Context Resolver 补全层（调用 4.2）。
- LLM fallback 层：规则无法确定 intent 时，调用 LLM 返回 JSON，做 schema 校验。
  - LLM 上下文最小化：只传当前用户输入、active namespace、资源引用和上一轮 finding 摘要。
- 澄清决策：缺少必要字段时设置 `needs_clarification=True`。
- M1 约束：收到 `diagnose_workload` 时返回不支持提示。

### 4.2 Context Resolver

```text
文件：src/k8s_troubleshooter/harness/context.py
```

实现：

- `SessionContext` 类：
  - `session_id: str`
  - `cluster_context: str`
  - `active_namespace: str`
  - `last_diagnosed_resources: list[ResourceRef]`
  - `active_findings: list[Finding]`
  - `last_diagnosis_results: list[DiagnosisResult]`
- `resolve_context(request: DiagnosisRequest, session: SessionContext) -> DiagnosisRequest`：
  - 补全缺失 namespace（从 session 或 kubeconfig 默认值）。
  - 补全缺失 resource name（从上一轮诊断结果匹配）。
  - 补全 symptoms（从 active findings 匹配）。
- `update_context(session: SessionContext, result: DiagnosisResult)`：诊断完成后更新 session。

### 4.3 Request Validator

```text
文件：src/k8s_troubleshooter/harness/validator.py
```

实现：

- `validate_request(request: DiagnosisRequest) -> ValidationResult`
- 校验规则：
  - intent 必须存在且为允许值。
  - scope.kind 必须为支持的类型（M1: Pod, Namespace）。
  - `diagnose_pod` 必须有 namespace 和 name。
  - `diagnose_namespace` 必须有 namespace。
  - `explain_finding` 必须有关联 finding（从 session context 验证）。
  - mode 必须为 `readonly`（M1 拒绝 dry_run/apply）。
  - depth 在允许范围内。
- 返回 `ValidationResult(valid, needs_clarification, missing_fields, clarification_question)`。

### 4.4 Tool Registry

```text
文件：src/k8s_troubleshooter/harness/tools.py
```

实现：

- `ToolRegistry` 类：注册和查找 `ToolSpec`。
- `register_tool(spec: ToolSpec, handler: Callable)`。
- `get_tool(name: str) -> tuple[ToolSpec, Callable] | None`。
- `list_tools() -> list[ToolSpec]`。
- M1 工具注册：在应用启动时注册 `list_pods`、`get_pod`、`get_pod_events`、`get_container_logs`、`get_owner_workload`、`get_pvc_metadata`、`check_configmap_exists`、`check_secret_exists`。
- 每个工具的 handler 封装对应 Collector 方法。
- `check_secret_exists` handler：调用 K8s API 后立即丢弃 `.data`，构造安全 DTO（`exists`, `type`, `keys`）。

### 4.5 Policy Guard

```text
文件：src/k8s_troubleshooter/harness/policy.py
```

实现：

- `PolicyGuard` 类，配置来自 `AppConfig`。
- `check_tool_call(tool_call: ToolCall, tool_spec: ToolSpec, context: PolicyContext) -> PolicyDecision`
- 策略规则：
  - 拒绝 `readonly=False` 的工具。
  - 限制可访问 namespace（如果配置了白名单）。
  - 限制单次诊断累计工具调用次数（默认 50）。
  - 限制日志行数（默认 200）和字节数。
  - `check_secret_exists` 只在 `enable_secret_check=True` 时允许。
- `check_llm_input(content: str) -> str`：
  - 检查并移除可能的 Secret value、token、证书。
  - 截断超长内容。
- 返回 `PolicyDecision(allowed, reason)`。

### 4.6 Tool Executor

```text
文件：src/k8s_troubleshooter/harness/executor.py
```

实现：

- `ToolExecutor` 类，持有 `ToolRegistry`、`PolicyGuard`、`TraceLogger`。
- `async execute(tool_call: ToolCall, policy_context: PolicyContext) -> ToolResult`：
  1. 从 registry 查找工具。
  2. 调用 Policy Guard 检查。
  3. 如果被拒绝，返回 `ToolResult(status="denied")`。
  4. 设置 timeout 执行 handler。
  5. 对 `check_secret_exists` 结果额外验证：确保返回值只有 `exists/type/keys`。
  6. 对返回结果做脱敏（调用 `redaction_policy`）。
  7. 写入 trace。
  8. 异常转换为 `ToolResult(status="error")`。
- `async execute_plan(tool_calls: list[ToolCall], policy_context: PolicyContext) -> list[ToolResult]`：顺序执行 tool plan。

### 4.7 Trace / Audit Logger

```text
文件：src/k8s_troubleshooter/harness/trace.py
```

实现：

- `TraceLogger` 类。
- `start_trace(request_id: str, user_input: str, parsed_intent: str)`
- `log_tool_call(tool_name: str, arguments: dict, status: str, duration_ms: int, result_summary: dict | None)`
  - 对 `check_secret_exists`：只记录 `namespace/name` 引用，不记录完整 K8s 对象。
- `log_policy_decision(tool_name: str, allowed: bool, reason: str)`
- `log_diagnosis_result(findings: list[str], llm_used: bool)`
- `get_trace() -> dict`：返回完整 trace 字典。
- Trace 输出到结构化日志文件（JSON Lines）。

### 4.8 测试

```text
tests/unit/harness/test_intent.py
tests/unit/harness/test_context.py
tests/unit/harness/test_validator.py
tests/unit/harness/test_policy.py
tests/unit/harness/test_executor.py
tests/unit/harness/test_trace.py
```

关键测试：

- Intent Parser 能解析 "看看 default namespace 的 pod" → `diagnose_namespace`。
- Intent Parser 能解析 "排查 default/demo-pod" → `diagnose_pod`。
- Intent Parser 对 `diagnose_workload` 返回不支持提示。
- Context Resolver 能从上一轮 OOMKilled finding 补全 Pod 名称。
- Validator 拒绝缺少 namespace 的 `diagnose_pod`。
- Validator 拒绝 `mode=dry_run`。
- Policy Guard 拒绝写操作。
- Policy Guard 在 `enable_secret_check=False` 时拒绝 `check_secret_exists`。
- Tool Executor 对被拒绝的调用返回 `status=denied`。
- Tool Executor 超时返回 `status=error`。
- Trace Logger 对 `check_secret_exists` 只记录资源引用。

**阶段交付**：Harness 所有组件通过单元测试。

---

## Phase 5: Diagnosis Engine 和规则诊断器

**目标**：实现诊断器注册机制、6 个 M1 规则诊断器和 LLM Fallback。

### 5.1 诊断器基类和注册

```text
文件：src/k8s_troubleshooter/diagnosis/base.py
文件：src/k8s_troubleshooter/diagnosis/registry.py
```

实现：

**base.py**：
```python
class BaseDiagnoser(ABC):
    @abstractmethod
    def can_diagnose(self, evidence: Evidence) -> bool: ...
    @abstractmethod
    def diagnose(self, evidence: Evidence) -> list[Finding]: ...
```

**registry.py**：
- `_DIAGNOSER_REGISTRY: dict[str, type[BaseDiagnoser]]`
- `@register_diagnoser(name: str)` 装饰器。
- `get_all_diagnosers() -> dict[str, type[BaseDiagnoser]]`。
- `load_diagnosers() -> list[BaseDiagnoser]`：使用 `pkgutil.iter_modules` 扫描 `diagnosis` 包，import 所有模块触发装饰器注册，返回实例列表。

### 5.2 Diagnosis Engine

```text
文件：src/k8s_troubleshooter/diagnosis/engine.py
```

实现：

- `DiagnosisEngine.__init__(diagnosers, llm_fallback)`
- `async diagnose(evidence, request) -> DiagnosisResult`：
  1. 遍历 diagnosers，对 `can_diagnose` 为 True 的调用 `diagnose`。
  2. 收集 `rule_findings`。
  3. 调用 `_should_use_llm(request, evidence, rule_findings)` 判断是否 fallback。
  4. 如需 fallback，调用 `llm_fallback.diagnose(evidence, rule_findings)`。
  5. `_merge_findings`：合并 rule + llm findings，按 severity 排序。
- `_should_use_llm` 条件（6 条）：
  - 无 rule findings。
  - 任一 finding confidence < 0.5。
  - 任一 finding.needs_llm_analysis 为 True。
  - request.depth == "deep"。
  - evidence 包含未分类错误日志。
  - 多个 high severity findings 并存。

### 5.3 ImagePull Diagnoser

```text
文件：src/k8s_troubleshooter/diagnosis/image_pull.py
```

实现：

- `can_diagnose`：container waiting reason 为 `ImagePullBackOff` 或 `ErrImagePull`。
- `diagnose`：
  - 检查 event message 区分子类型：
    - `not found` → `image_not_found`（high, confidence 0.95）
    - `unauthorized` / `authentication required` / `pull access denied` → `image_auth_failed`（high, 0.91）
    - DNS / timeout / TLS → `image_registry_unreachable`（high, 0.85）
    - 仅 `ImagePullBackOff` 无更多信息 → `image_pull_failed`（medium, 0.6, needs_llm_analysis=True）
  - 检查 `imagePullSecrets` 和 SA 默认 `imagePullSecrets`。
  - 生成 recommendations。

### 5.4 CrashLoop Diagnoser

```text
文件：src/k8s_troubleshooter/diagnosis/crash_loop.py
```

实现：

- `can_diagnose`：waiting reason 为 `CrashLoopBackOff` 且 restart_count > 0。
- `diagnose`：
  - 检查 terminated reason 和 exit code。
  - 检查 previous logs 中的关键错误。
  - 检查 probe 配置（liveness probe 杀容器）。
  - 检查 ConfigMap/Secret/env 引用。
  - 生成 finding（根据 exit code 和日志调整 confidence）。

### 5.5 OOM Diagnoser

```text
文件：src/k8s_troubleshooter/diagnosis/oom.py
```

实现：

- `can_diagnose`：terminated reason 为 `OOMKilled` 或 exit code 为 137。
- `diagnose`：
  - 提取 memory request/limit。
  - 检查 QoS class。
  - 检查 previous logs 中的内存相关错误。
  - 生成 finding，recommendations 包含调整 limit 和检查内存泄漏。

### 5.6 Scheduling Diagnoser

```text
文件：src/k8s_troubleshooter/diagnosis/scheduling.py
```

实现：

- `can_diagnose`：phase 为 `Pending` 且无 nodeName 且 events 中有 `FailedScheduling`。
- `diagnose`：
  - 解析 scheduler event message 关键词：
    - `Insufficient cpu` / `Insufficient memory` → 资源不足。
    - `didn't match Pod's node affinity/selector` → affinity/selector 不满足。
    - `had taint ... that the pod didn't tolerate` → 缺少 toleration。
    - `persistentvolumeclaim ... not found` / `unbound` → PVC 问题。
    - `node(s) were unschedulable` → 节点被 cordon（标注需后续 Node Diagnoser 确认）。
  - 检查 Pod spec 中的 requests、nodeSelector、affinity、tolerations。
  - 检查 PVC 绑定状态。

### 5.7 ConfigError Diagnoser

```text
文件：src/k8s_troubleshooter/diagnosis/config_error.py
```

实现：

- `can_diagnose`：waiting reason 为 `CreateContainerConfigError` 或 `CreateContainerError`。
- `diagnose`：
  - 检查 event message 中的 ConfigMap/Secret/SA 引用。
  - 交叉验证引用的 ConfigMap 是否存在（通过 evidence 中的 related_resources）。
  - 检查 env key 和 volume mount key。
  - 生成 finding。

### 5.8 Probe Diagnoser

```text
文件：src/k8s_troubleshooter/diagnosis/probe.py
```

实现：

- `can_diagnose`：events 中有 reason 为 `Unhealthy` 且 message 指向 liveness/readiness/startup probe。
- `diagnose`：
  - 识别 probe 类型（HTTP/TCP/exec）。
  - 提取 probe 配置（path, port, command, failureThreshold, initialDelaySeconds, periodSeconds, timeoutSeconds）。
  - 检查 restart count（liveness 失败导致重启）。
  - 检查容器日志中的启动状态。
  - 生成 finding 和 recommendations（调整 initialDelaySeconds、检查 path/port 等）。

### 5.9 LLM Fallback Diagnoser

```text
文件：src/k8s_troubleshooter/diagnosis/llm_fallback.py
```

实现：

- `LLMFallbackDiagnoser.__init__(llm_provider: LLMProvider)`
- `async diagnose(evidence: Evidence, rule_findings: list[Finding]) -> list[Finding]`：
  - 构建 prompt：包含脱敏后的 evidence 摘要、已有 rule findings（如果有）、请求 LLM 输出结构化 JSON findings。
  - 调用 `llm_provider.chat`。
  - 解析 LLM 返回的 JSON，校验 schema。
  - 所有 LLM findings 的 source 设为 `"llm"`。
  - 解析失败时返回空列表并记录警告。

### 5.10 测试

```text
tests/unit/diagnosis/test_registry.py
tests/unit/diagnosis/test_engine.py
tests/unit/diagnosis/test_image_pull.py
tests/unit/diagnosis/test_crash_loop.py
tests/unit/diagnosis/test_oom.py
tests/unit/diagnosis/test_scheduling.py
tests/unit/diagnosis/test_config_error.py
tests/unit/diagnosis/test_probe.py
tests/unit/diagnosis/test_llm_fallback.py
```

每个诊断器至少覆盖：

- 正向匹配（can_diagnose 返回 True，diagnose 返回正确 finding）。
- 负向匹配（can_diagnose 返回 False）。
- 边界情况（如 exit code 137 但 terminated reason 非 OOMKilled）。

使用 `tests/fixtures/evidence/` 中的 fixture：

```text
tests/fixtures/evidence/image-pull-not-found.json
tests/fixtures/evidence/image-pull-auth-failed.json
tests/fixtures/evidence/crash-loop-exit-1.json
tests/fixtures/evidence/crash-loop-probe-kill.json
tests/fixtures/evidence/oom-killed.json
tests/fixtures/evidence/pending-insufficient-cpu.json
tests/fixtures/evidence/pending-no-toleration.json
tests/fixtures/evidence/configmap-missing.json
tests/fixtures/evidence/probe-liveness-fail.json
```

Engine 测试：

- 验证 `load_diagnosers()` 能发现所有已注册诊断器。
- 验证无 rule findings 时触发 LLM fallback。
- 验证 confidence < 0.5 时触发 LLM fallback。
- 验证 `_merge_findings` 按 severity 排序。

**阶段交付**：所有诊断器通过 fixture 测试，Engine 流程验证通过。

---

## Phase 6: LLM Provider

**目标**：实现可插拔 LLM 接口和 OpenAI 兼容实现。

### 6.1 LLM Provider 接口

```text
文件：src/k8s_troubleshooter/llm/provider.py
```

实现：

- `LLMProvider` ABC：`chat`（非流式）和 `chat_stream`（流式，返回 `AsyncIterator[str]`）。

### 6.2 OpenAI Provider

```text
文件：src/k8s_troubleshooter/llm/openai_provider.py
```

实现：

- `OpenAIProvider(api_key, base_url, model)`
- 使用 `openai.AsyncOpenAI` 客户端。
- `chat`：调用 `client.chat.completions.create(stream=False)`。
- `chat_stream`：调用 `client.chat.completions.create(stream=True)`，yield delta content。
- 错误处理：API key 缺失、网络错误、rate limit。

### 6.3 Prompt 模板

```text
文件：src/k8s_troubleshooter/llm/prompts.py
```

实现：

- `INTENT_PARSE_PROMPT`：用于 Intent Parser LLM fallback 的 system prompt。指导 LLM 从用户输入提取 intent/scope/symptoms 并返回 JSON。
- `LLM_FALLBACK_DIAGNOSIS_PROMPT`：用于 LLM Fallback Diagnoser 的 system prompt。指导 LLM 基于 evidence 做诊断并返回结构化 findings JSON。
- `EXPLAIN_FINDING_PROMPT`：用于 `explain_finding` intent 的 system prompt。指导 LLM 对已有 finding 做详细解释和建议。
- `REPORT_GENERATION_PROMPT`：用于生成自然语言报告的 system prompt。

### 6.4 测试

```text
tests/unit/llm/test_openai_provider.py
tests/unit/llm/test_prompts.py
```

- Mock `AsyncOpenAI` 测试 chat 和 chat_stream。
- 测试 prompt 模板渲染。

**阶段交付**：LLM Provider 通过 mock 测试，prompt 模板完整。

---

## Phase 7: Diagnosis Orchestrator 和 Reporter

**目标**：实现 Orchestrator 编排诊断流程，实现 Reporter 输出结构化和自然语言报告。

### 7.1 Diagnosis Orchestrator

```text
文件：src/k8s_troubleshooter/agent/orchestrator.py
```

实现：

- `DiagnosisOrchestrator.__init__(tool_executor, llm_provider, config)`：
  - 调用 `load_diagnosers()` 构建诊断器列表。
  - 创建 `LLMFallbackDiagnoser`。
  - 创建 `DiagnosisEngine`。
  - 创建 `EvidenceNormalizer`。
- `async diagnose(request: DiagnosisRequest, session: SessionContext) -> DiagnosisResult`：
  - 根据 intent 分发到不同流程。
- `_diagnose_pod` 流程：
  1. 生成 tool plan：`[get_pod, get_pod_events, get_container_logs (current), get_container_logs (previous), get_owner_workload]`。根据 Pod spec 中的引用可选添加 `get_pvc_metadata`、`check_configmap_exists`、`check_secret_exists`。
  2. 将 tool plan 交给 `tool_executor.execute_plan()`。
  3. 消费 tool results，调用 normalizer 构建 evidence。
  4. 调用 `engine.diagnose(evidence, request)`。
  5. 返回 `DiagnosisResult`。
- `_diagnose_namespace` 流程：
  1. 生成 tool plan：`[list_pods]`。
  2. 执行并获取 Pod 列表。
  3. 过滤异常 Pod（phase != Running/Succeeded，或 restart count 高，或 container not ready）。
  4. 对每个异常 Pod（最多 `max_pods_per_scan` 个）执行 `_diagnose_pod`。
  5. 汇总所有 findings。
- `_explain_finding` 流程：
  1. 从 session context 取出指定 finding 及其关联 evidence。
  2. 可选生成补充 tool plan（`get_pod` 获取当前状态、`get_pod_events` 获取最新 events）。
  3. 执行补充工具。
  4. 将 finding + evidence 传入 LLM 生成解释。
  5. 返回解释结果。

### 7.2 Reporter

```text
文件：src/k8s_troubleshooter/report/formatter.py
文件：src/k8s_troubleshooter/report/streaming.py
```

**formatter.py**：
- `format_json(result: DiagnosisResult) -> str`：输出结构化 JSON。
- `format_text(result: DiagnosisResult) -> str`：输出纯文本报告。

**streaming.py**：
- `async stream_report(result: DiagnosisResult, llm_provider: LLMProvider) -> AsyncIterator[str]`：
  - 先输出确定性部分（诊断对象、状态、rule findings）。
  - 如有 LLM findings，标注 "以下为 LLM 推理结论"。
  - 调用 LLM 流式生成自然语言解释和建议。
  - 使用 rich Markdown 格式化。

### 7.3 测试

```text
tests/unit/agent/test_orchestrator.py
tests/unit/report/test_formatter.py
tests/unit/report/test_streaming.py
```

- Orchestrator：mock tool_executor，验证 `_diagnose_pod` 生成正确 tool plan 顺序。
- Orchestrator：验证 `_diagnose_namespace` 过滤异常 Pod 并限制数量。
- Orchestrator：验证 `_explain_finding` 从 session context 取 finding。
- Reporter：验证 JSON 输出包含所有必要字段。
- Reporter：验证文本报告区分 rule 和 llm findings。

**阶段交付**：Orchestrator 编排逻辑通过测试，Reporter 输出格式正确。

---

## Phase 8: Terminal ChatBot 和端到端集成

**目标**：实现终端交互，组装所有组件，端到端可用。

### 8.1 Chat Session

```text
文件：src/k8s_troubleshooter/chat/session.py
```

实现：

- `ChatSession` 类，管理一次完整的 ChatBot 会话。
- 持有 `SessionContext`、`DiagnosisOrchestrator`、`ToolExecutor`、`LLMProvider`、`TraceLogger`。
- `async handle_input(user_input: str) -> AsyncIterator[str]`：
  1. 调用 Intent Parser 解析意图。
  2. 调用 Context Resolver 补全上下文。
  3. 调用 Request Validator 校验。
  4. 如需澄清，yield 澄清问题并返回。
  5. 调用 Orchestrator 执行诊断。
  6. 更新 SessionContext。
  7. 调用 Reporter 流式输出结果。
  8. 写入 Trace。

### 8.2 Terminal UI

```text
文件：src/k8s_troubleshooter/chat/terminal.py
```

实现：

- 使用 `prompt_toolkit` 提供交互式输入（支持历史、补全）。
- 使用 `rich` 渲染 Markdown 输出。
- 启动时显示集群连接信息。
- 支持 streaming 输出（逐 chunk 渲染）。
- 支持 Ctrl+C 中断当前诊断。
- 支持 `/quit` 或 `/exit` 退出。
- 支持 `/context` 显示当前 session context。

### 8.3 Main 入口

```text
文件：src/k8s_troubleshooter/main.py
```

实现：

- `async run(config: AppConfig)`：
  1. 创建 KubeClient 并验证连接。
  2. 创建 LLMProvider（如果配置了）。
  3. 创建 ToolRegistry 并注册 M1 工具。
  4. 创建 PolicyGuard。
  5. 创建 ToolExecutor。
  6. 创建 TraceLogger。
  7. 创建 DiagnosisOrchestrator。
  8. 创建 ChatSession。
  9. 启动 Terminal UI 循环。

### 8.4 工具注册

```text
文件：src/k8s_troubleshooter/harness/tools.py（扩展）
```

实现：

- `register_m1_tools(registry: ToolRegistry, kube_client: KubeClient, config: AppConfig)`：
  - 为每个 M1 工具创建 ToolSpec 和 handler。
  - handler 调用对应 Collector 方法。
  - `check_secret_exists` handler 实现安全 DTO 构造。
  - `check_configmap_exists` handler 返回存在性和 key 列表。
  - `get_pvc_metadata` handler 返回 PVC 状态、accessModes、storageClassName。

### 8.5 集成测试

```text
tests/integration/test_end_to_end.py
```

使用 kind 集群：

- 部署一个 ImagePullBackOff Pod，验证完整诊断流程。
- 部署一个 OOMKilled Pod，验证 OOM 诊断。
- 部署一个 Pending Pod（资源不足），验证 scheduling 诊断。
- 部署一个 ConfigMap 缺失 Pod，验证 config error 诊断。
- 验证多轮对话上下文传递。
- 验证 Trace 记录完整。
- 验证 Policy Guard 拒绝 Secret 读取（未启用时）。

### 8.6 手动验收

在 kind 或真实集群上运行 ChatBot，验证以下场景：

```text
验收清单：
[ ] 启动时显示集群连接信息
[ ] "default namespace 有什么异常的 pod" → 扫描并列出异常 Pod
[ ] "排查 default/demo-pod" → 输出完整诊断报告
[ ] "详细看看那个 OOM 的" → 上下文补全并深入诊断
[ ] "这个 finding 是什么意思" → explain_finding 流程
[ ] streaming 输出正常
[ ] Ctrl+C 中断诊断
[ ] /quit 退出
[ ] 无 LLM 配置时，规则诊断正常，LLM fallback 跳过并提示
[ ] --enable-secret-check 启用后 check_secret_exists 可用
```

**阶段交付**：Terminal ChatBot 端到端可用，通过集成测试和手动验收。

---

## 阶段依赖关系

```text
Phase 1: 项目骨架和配置
  ↓
Phase 2: Kubernetes 连接和 Collectors ──┐
  ↓                                      │
Phase 3: 数据模型和 Evidence Normalizer ──┤
  ↓                                      │
Phase 6: LLM Provider ──────────────────┤ (Phase 2/3/6 可并行)
  ↓                                      │
Phase 4: Agent Harness ←─────────────────┘ (依赖 Phase 2 的 Collector、Phase 3 的数据模型)
  ↓
Phase 5: Diagnosis Engine 和规则诊断器 (依赖 Phase 3 的数据模型、Phase 4 的 registry)
  ↓
Phase 7: Orchestrator 和 Reporter (依赖 Phase 4/5/6)
  ↓
Phase 8: Terminal ChatBot 和端到端集成 (依赖所有)
```

可并行的工作：

- Phase 2（Collectors）和 Phase 3（数据模型）和 Phase 6（LLM Provider）互相独立，可并行开发。
- Phase 4（Harness）和 Phase 5（Diagnosers）在数据模型确定后可部分并行（Harness 的 Tool Registry/Executor 和 Diagnosers 的 engine/注册机制独立）。

## 风险和注意事项

### kubernetes Python 客户端异步适配

kubernetes 官方 Python 客户端是同步的。所有 Collector 方法需要用 `asyncio.to_thread` 包装。如果性能不满足要求，考虑替换为 `kr8s`（异步原生）或 `lightkube`。

### LLM Provider 不可用时的降级

M1 必须支持无 LLM 配置运行。此时：
- Intent Parser 只用规则解析，无法解析时直接要求澄清。
- LLM Fallback 跳过，报告中注明 "LLM 未配置，仅展示规则诊断结果"。
- `explain_finding` 返回 finding 的结构化信息，不做 LLM 解释。
- streaming 报告回退为直接输出文本。

### 测试环境

- 单元测试：mock kubernetes client 和 LLM provider，无需真实集群。
- 集成测试：使用 kind 集群。CI 中可选跳过。
- 回归测试：纯 fixture 驱动，无外部依赖。

### Secret 安全

实现 `check_secret_exists` handler 时，必须在代码层面确保：
1. K8s API 返回的 Secret 对象在 handler 内部立即丢弃 `.data`。
2. 构造的安全 DTO 只含 `exists`、`type`、`keys`。
3. 原始 Secret 对象的引用不逃逸出 handler 作用域。
4. 单元测试必须验证 ToolResult.data 中不含 `.data` 字段。

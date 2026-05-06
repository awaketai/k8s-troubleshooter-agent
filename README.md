# k8s-troubleshooter-agent

Kubernetes 问题诊断 Agent，基于 LLM 意图理解 + 规则引擎诊断的双层架构，通过交互式终端对 Pod 进行自动化故障排查。

## 功能特性

- **LLM 意图理解** — 自然语言输入由 LLM 解析，准确提取诊断意图、Pod 名称和症状（支持中英文混合）
- **规则引擎诊断** — 内置 6 种常见故障的自动检测：ImagePullBackOff、CrashLoopBackOff、OOMKilled、调度失败、配置错误、探针失败
- **LLM 推理兜底** — 规则无法覆盖或置信度不足时，自动调用 LLM 进行深度分析
- **双模式运行** — 配置 LLM 时为完整模式（LLM 意图理解 + 诊断推理）；未配置时降级为纯规则模式（关键词匹配 + 规则诊断）
- **交互式终端** — Rich Markdown 渲染、诊断进度动画、非 K8s 输入友好提示
- **安全策略** — 只读访问、敏感信息脱敏、命名空间白名单、Secret 安全检查需显式开启
- **诊断追踪** — 每次诊断生成 Trace 记录，包含完整的工具调用链和策略决策

## 安装

要求 Python >= 3.11。

```bash
pip install -e .
```

或使用 uv：

```bash
uv pip install -e .
```

## 快速开始

```bash
# 完整模式（推荐）：配置 .env 中的 LLM 信息
k8s-troubleshooter

# 指定 namespace
k8s-troubleshooter --namespace production

# 纯规则模式（无需 LLM，仅支持关键词匹配和 ns/name 格式输入）
k8s-troubleshooter
```

启动后进入交互式终端：

```
> 看看这个 pod 为什么启动失败：test-crashloop
⠋ 正在分析...

诊断对象: Pod/default/test-crashloop
当前状态: CrashLoopBackOff
...

> default/demo-pod                  # kubectl 风格快速诊断
> 这个 finding 是什么意思
> 你好                               # 非 K8s 输入有友好提示
```

## 配置

配置支持三种方式，优先级从高到低：**命令行参数 > 配置文件 > 默认值**。

### 命令行参数

```
k8s-troubleshooter [OPTIONS]

Options:
  --kubeconfig PATH          kubeconfig 文件路径（默认 ~/.kube/config）
  --context TEXT             kubeconfig context 名称
  --config PATH              YAML 配置文件路径
  --namespace TEXT           默认 namespace
  --max-tool-calls INT       单次诊断最大工具调用次数（默认 50）
  --log-tail-lines INT       每个容器最多获取的日志行数（默认 200）
  --enable-secret-check      启用 Secret 元数据检查（需要 secrets get 权限）
```

### 配置文件

创建 YAML 文件并通过 `--config` 指定：

```yaml
kubeconfig: ~/.kube/config
context: my-cluster
namespace: default

llm:
  provider: openai
  api_key_env: OPENAI_API_KEY
  base_url_env: OPENAI_BASE_URL
  model_env: OPENAI_MODEL

max_tool_calls: 50
log_tail_lines: 200
max_pods_per_scan: 10
enable_secret_check: false
allowed_namespaces:
  - default
  - production
  - staging
```

### LLM 配置

LLM 同时用于**意图理解**（解析自然语言输入）和**诊断推理**（规则未覆盖时的深度分析）。推荐配置以获得最佳体验。

通过 `.env` 文件或环境变量配置，兼容 OpenAI API 格式：

| 环境变量 | 说明 | 默认值 |
|---|---|---|
| `OPENAI_API_KEY` | API 密钥 | 无（不配置则纯规则模式） |
| `OPENAI_MODEL` | 模型名称 | 无 |
| `OPENAI_BASE_URL` | API 基础 URL | `https://api.openai.com/v1` |

如需使用兼容 OpenAI 格式的第三方服务（如 Azure OpenAI、本地部署等），在 `.env` 中设置：

```bash
OPENAI_BASE_URL=https://your-api-endpoint/v1
```

也可以通过 `config.yaml` 自定义环境变量名：

```yaml
llm:
  base_url_env: CUSTOM_LLM_BASE_URL
```

### 完整配置项

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `kubeconfig` | string | `~/.kube/config` | kubeconfig 文件路径 |
| `context` | string | current-context | kubeconfig context |
| `namespace` | string | `default` | 默认 namespace |
| `llm.provider` | string | `openai` | LLM 提供商 |
| `llm.api_key_env` | string | `OPENAI_API_KEY` | 存放 API Key 的环境变量名 |
| `llm.base_url_env` | string | `OPENAI_BASE_URL` | 存放 base URL 的环境变量名 |
| `llm.model_env` | string | `OPENAI_MODEL` | 存放模型名的环境变量名 |
| `max_tool_calls` | int | `50` | 单次诊断最大工具调用次数 |
| `log_tail_lines` | int | `200` | 每容器最大日志行数 |
| `max_pods_per_scan` | int | `10` | namespace 扫描时最多检查的异常 Pod 数 |
| `enable_secret_check` | bool | `false` | 是否启用 Secret 存在性检查 |
| `allowed_namespaces` | list | `null`（不限） | 允许诊断的 namespace 白名单 |

## 使用说明

### 交互式命令

| 命令 | 说明 |
|---|---|
| `/quit`, `/exit` | 退出 |
| `/context` | 查看当前会话上下文 |
| `/help` | 显示帮助 |

### 诊断模式

**Pod 诊断** — 对单个 Pod 进行深度诊断：

```
> 看看这个 pod 为什么启动失败：test-crashloop
> 排查 default/demo-pod 为什么起不来
> default/demo-pod                              # kubectl 风格，无需 LLM
```

**Namespace 扫描** — 扫描 namespace 下所有异常 Pod：

```
> 看看 production namespace 有什么异常的 pod
> 扫描 staging 下的 pod
```

**Finding 解释** — 对上一次诊断结果进行解释：

```
> 这个 finding 是什么意思
> 解释一下那个 OOMKilled 的原因
```

### 纯规则模式关键词

未配置 LLM 时，意图解析依赖关键词匹配。配置 LLM 后自然语言任意表达均可识别。

**症状关键词**：

| 关键词 | 对应症状 |
|---|---|
| `oom`、`oomkilled` | OOMKilled |
| `imagepull`、`image pull` | ImagePullBackOff |
| `crashloop`、`crash loop` | CrashLoopBackOff |
| `pending` | Pending |
| `configerror`、`config error` | CreateContainerConfigError |
| `probe`、`探针`、`unhealthy` | ProbeFailure |

**深度控制**：

| 关键词 | 深度 |
|---|---|
| `快速`、`quick` | quick |
| `详细`、`深入`、`deep` | deep |
| （默认） | normal |

## 诊断流程

```
用户输入
  │
  ├─ "ns/name" 格式? → regex 快速路径，直接诊断（零 LLM 开销）
  │
  ├─ LLM 可用? → LLM 意图解析（自然语言 → intent + scope + symptoms）
  │   │              识别非 K8s 输入 → 友好提示
  │   └─ LLM 失败 → regex 降级
  │
  ├─ 纯规则模式 → 关键词匹配（regex fallback）
  │
  ├─ 上下文补全 → 请求校验 → 策略守卫
  │
  ├─ 工具执行计划：
  │   get_pod → get_pod_events → get_container_logs (当前+上次)
  │   → get_owner_workload → get_pvc_metadata → check_configmap_exists
  │   → check_secret_exists
  │
  ├─ 证据收集与归一化
  │
  ├─ 规则引擎诊断（6 种内建 diagnoser 自动匹配）
  │   ├─ 命中 → 返回 finding
  │   └─ 未命中或置信度低 → LLM 推理
  │
  └─ 报告生成（规则结果 + 可选 LLM 详细报告）
```

## 内建诊断规则

| Diagnoser | 触发条件 | 检测内容 |
|---|---|---|
| ImagePull | `ImagePullBackOff` / `ErrImagePull` | 镜像不存在、认证失败、仓库不可达 |
| CrashLoop | `CrashLoopBackOff` | 崩溃原因分析，关联 ConfigMap/Secret 配置 |
| OOM | `OOMKilled` | 内存限制分析，按 QoS 类型给出建议 |
| Scheduling | `Pending` + 调度事件 | 资源不足、节点选择器/亲和性、容忍度、PVC 挂载 |
| ConfigError | `CreateContainerConfigError` | ConfigMap/Secret 缺失，环境变量引用校验 |
| Probe | `Unhealthy` 事件 + liveness/readiness/startup | 探针类型（HTTP/TCP/Exec）、失败原因分析 |

## 安全机制

- **只读访问** — 所有工具调用均为只读操作，不会修改集群资源
- **敏感信息脱敏** — 日志和 LLM 输入自动脱敏 password/token/secret/certificate 等模式
- **Secret 检查** — 默认关闭，需 `--enable-secret-check` 显式开启；仅返回 type 和 keys，不返回 values
- **命名空间白名单** — `allowed_namespaces` 配置后，仅允许诊断指定 namespace
- **工具调用上限** — 单次诊断最多调用 `max_tool_calls` 次工具，防止资源消耗
- **策略守卫** — 同时检查会话 namespace 和工具调用参数中的 namespace

## RBAC 权限

Agent 需要以下最小权限：

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: k8s-troubleshooter
rules:
  - apiGroups: [""]
    resources: ["pods", "pods/log", "events", "persistentvolumeclaims", "configmaps"]
    verbs: ["get", "list"]
  - apiGroups: ["apps"]
    resources: ["deployments", "replicasets", "statefulsets", "daemonsets"]
    verbs: ["get"]
  - apiGroups: [""]
    resources: ["secrets"]
    verbs: ["get"]  # 仅在 --enable-secret-check 时需要
```

## 项目结构

```
src/k8s_troubleshooter/
├── cli.py                  # CLI 入口
├── config.py               # 配置管理
├── main.py                 # 启动逻辑
├── agent/
│   └── orchestrator.py     # 诊断编排器
├── chat/
│   ├── session.py          # 会话管理
│   └── terminal.py         # 终端 UI
├── diagnosis/
│   ├── base.py             # 诊断器基类
│   ├── registry.py         # 诊断器注册与发现
│   ├── engine.py           # 诊断引擎（规则 + LLM 合并）
│   ├── llm_fallback.py     # LLM 兜底诊断
│   ├── image_pull.py       # ImagePull 诊断
│   ├── crash_loop.py       # CrashLoop 诊断
│   ├── oom.py              # OOM 诊断
│   ├── scheduling.py       # 调度失败诊断
│   ├── config_error.py     # 配置错误诊断
│   ├── probe.py            # 探针失败诊断
│   └── finding.py          # Finding 数据模型
├── evidence/
│   ├── model.py            # 证据数据模型
│   └── normalizer.py       # K8s 对象 → 证据归一化
├── harness/
│   ├── schema.py           # 请求/响应模型
│   ├── intent.py           # 自然语言意图解析
│   ├── context.py          # 会话上下文
│   ├── validator.py        # 请求校验
│   ├── policy.py           # 策略守卫
│   ├── tools.py            # 工具注册表
│   ├── tool_setup.py       # M1 工具注册
│   ├── executor.py         # 工具执行器
│   └── trace.py            # 诊断追踪
├── kube/
│   ├── client.py           # Kubernetes 客户端
│   ├── pod_collector.py    # Pod 收集
│   ├── event_collector.py  # 事件收集
│   ├── log_collector.py    # 日志收集
│   └── workload_collector.py # 工作负载收集
├── llm/
│   ├── provider.py         # LLM 提供者抽象
│   ├── openai_provider.py  # OpenAI 实现
│   └── prompts.py          # Prompt 模板
└── report/
    ├── formatter.py        # 报告格式化
    └── streaming.py        # 流式报告输出
```

## 开发

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest tests/ -v

# 查看测试覆盖
pytest tests/ --cov=k8s_troubleshooter
```

## 许可

MIT

# Institutions

我想要构建一个 k8s 问题排查的 agent，这个 agent 可以排查 k8s 出现的各种问题，比如 pod 因为资源限制启动失败，或者因为镜像原因启动失败等，这个 agent    该如何构建

问题排查 Agent 的使用方式：ChatBot 形式

Agent 的 LLM 后端：可插拔设计，支持多种后端

排查范围覆盖哪些 k8s 问题：覆盖所有问题，部署/配置问题等
from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    provider: str = "openai"
    api_key_env: str = "OPENAI_API_KEY"
    base_url_env: str = "OPENAI_BASE_URL"
    model_env: str = "OPENAI_MODEL"


class AppConfig(BaseModel):
    kubeconfig: str | None = None
    context: str | None = None
    namespace: str | None = None
    llm: LLMConfig = Field(default_factory=LLMConfig)
    max_tool_calls: int = 50
    log_tail_lines: int = 200
    max_pods_per_scan: int = 10
    enable_secret_check: bool = False
    allowed_namespaces: list[str] | None = None

    @property
    def resolved_kubeconfig(self) -> str:
        if self.kubeconfig:
            return self.kubeconfig
        return str(Path.home() / ".kube" / "config")

    @property
    def resolved_api_key(self) -> str | None:
        return os.environ.get(self.llm.api_key_env)

    @property
    def resolved_base_url(self) -> str:
        return os.environ.get(self.llm.base_url_env) or "https://api.openai.com/v1"

    @property
    def resolved_model(self) -> str | None:
        return os.environ.get(self.llm.model_env)


def load_config(config_path: str | None = None, **overrides) -> AppConfig:
    data: dict = {}
    if config_path:
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        with open(path) as f:
            data = yaml.safe_load(f) or {}

    for key, value in overrides.items():
        if value is not None:
            data[key] = value

    return AppConfig(**data)

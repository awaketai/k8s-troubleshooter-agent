from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from k8s_troubleshooter.config import AppConfig, load_config


class TestAppConfig:
    def test_defaults(self):
        config = AppConfig()
        assert config.enable_secret_check is False
        assert config.max_tool_calls == 50
        assert config.log_tail_lines == 200
        assert config.max_pods_per_scan == 10
        assert config.kubeconfig is None
        assert config.context is None
        assert config.namespace is None

    def test_resolved_kubeconfig_default(self):
        config = AppConfig()
        assert config.resolved_kubeconfig == str(Path.home() / ".kube" / "config")

    def test_resolved_kubeconfig_explicit(self):
        config = AppConfig(kubeconfig="/custom/kubeconfig")
        assert config.resolved_kubeconfig == "/custom/kubeconfig"

    def test_resolved_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        config = AppConfig()
        assert config.resolved_api_key == "test-key"

    def test_resolved_api_key_missing(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        config = AppConfig()
        assert config.resolved_api_key is None

    def test_resolved_model_from_env(self, monkeypatch):
        monkeypatch.setenv("OPENAI_MODEL", "gpt-4o")
        config = AppConfig()
        assert config.resolved_model == "gpt-4o"

    def test_resolved_model_missing(self, monkeypatch):
        monkeypatch.delenv("OPENAI_MODEL", raising=False)
        config = AppConfig()
        assert config.resolved_model is None


class TestLoadConfig:
    def test_load_from_yaml(self):
        data = {
            "kubeconfig": "/custom/kubeconfig",
            "namespace": "production",
            "max_tool_calls": 100,
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(data, f)
            f.flush()
            config = load_config(config_path=f.name)

        assert config.kubeconfig == "/custom/kubeconfig"
        assert config.namespace == "production"
        assert config.max_tool_calls == 100
        os.unlink(f.name)

    def test_cli_overrides_yaml(self):
        data = {"namespace": "default", "max_tool_calls": 30}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(data, f)
            f.flush()
            config = load_config(
                config_path=f.name,
                namespace="override-ns",
                max_tool_calls=100,
            )

        assert config.namespace == "override-ns"
        assert config.max_tool_calls == 100
        os.unlink(f.name)

    def test_missing_config_file(self):
        with pytest.raises(FileNotFoundError, match="Config file not found"):
            load_config(config_path="/nonexistent/config.yaml")

    def test_no_config_file(self):
        config = load_config()
        assert config.enable_secret_check is False

    def test_none_overrides_ignored(self):
        config = load_config(namespace=None)
        assert config.namespace is None

    def test_llm_config_defaults(self):
        config = load_config()
        assert config.llm.provider == "openai"
        assert config.llm.api_key_env == "OPENAI_API_KEY"
        assert config.llm.base_url_env == "OPENAI_BASE_URL"
        assert config.resolved_base_url == "https://api.openai.com/v1"
        assert config.llm.model_env == "OPENAI_MODEL"

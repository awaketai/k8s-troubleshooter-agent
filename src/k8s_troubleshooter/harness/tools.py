from __future__ import annotations

from typing import Any, Callable

from k8s_troubleshooter.harness.schema import ToolSpec


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, tuple[ToolSpec, Callable]] = {}

    def register(self, spec: ToolSpec, handler: Callable) -> None:
        self._tools[spec.name] = (spec, handler)

    def get(self, name: str) -> tuple[ToolSpec, Callable] | None:
        return self._tools.get(name)

    def list_tools(self) -> list[ToolSpec]:
        return [spec for spec, _ in self._tools.values()]

    def has(self, name: str) -> bool:
        return name in self._tools

from __future__ import annotations

import importlib
import pkgutil
from typing import Type

from k8s_troubleshooter.diagnosis.base import BaseDiagnoser

_REGISTRY: dict[str, Type[BaseDiagnoser]] = {}


def register_diagnoser(name: str):
    def wrapper(cls: Type[BaseDiagnoser]) -> Type[BaseDiagnoser]:
        _REGISTRY[name] = cls
        return cls
    return wrapper


def get_all_diagnosers() -> dict[str, Type[BaseDiagnoser]]:
    return dict(_REGISTRY)


def load_diagnosers() -> list[BaseDiagnoser]:
    import k8s_troubleshooter.diagnosis as diagnosis_pkg

    for module_info in pkgutil.iter_modules(diagnosis_pkg.__path__):
        importlib.import_module(f"{diagnosis_pkg.__name__}.{module_info.name}")

    return [cls() for cls in _REGISTRY.values()]

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

@dataclass(slots=True)
class RequestBase:
    request_id: str
    mode: str

@dataclass(slots=True)
class GenerationRequest(RequestBase):
    change_request: dict[str, Any]
    target: dict[str, Any]
    project_context: dict[str, Any]
    reference_context: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)
    context_metrics: dict[str, Any] = field(default_factory=dict)

@dataclass(slots=True)
class RepairRequest(RequestBase):
    previous_generation_request_id: str
    change_request: dict[str, Any]
    error_context: dict[str, Any]
    previous_artifact: dict[str, Any]
    project_context: dict[str, Any]
    reference_context: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)

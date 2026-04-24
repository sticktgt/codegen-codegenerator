from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
from codegenerator.models.artifacts import CodeArtifact, TestArtifact

@dataclass(slots=True)
class GenerationResult:
    request_id: str
    status: str
    code_artifact: CodeArtifact | None = None
    test_artifact: TestArtifact | None = None
    planner_result: dict[str, Any] | None = None
    test_planner_result: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)
    trace_path: str | None = None
    llm_usage: dict[str, Any] | None = None
    error_type: str | None = None
    message: str | None = None
    def to_dict(self) -> dict[str, Any]:
        return {
            'request_id': self.request_id,
            'status': self.status,
            'code_artifact': self.code_artifact.to_dict() if self.code_artifact else None,
            'test_artifact': self.test_artifact.to_dict() if self.test_artifact else None,
            'planner_result': self.planner_result,
            'test_planner_result': self.test_planner_result,
            'warnings': self.warnings,
            'trace_path': self.trace_path,
            'llm_usage': self.llm_usage,
            'error_type': self.error_type,
            'message': self.message,
        }

from __future__ import annotations
from dataclasses import dataclass
from typing import Any

@dataclass(slots=True)
class CodeArtifact:
    operation: str
    target_qualname: str
    target_file: str
    code: str
    insert_after: str | None = None
    def to_dict(self) -> dict[str, Any]:
        return {'operation': self.operation, 'target_qualname': self.target_qualname, 'target_file': self.target_file, 'code': self.code, 'insert_after': self.insert_after}

@dataclass(slots=True)
class TestArtifact:
    file_path: str
    source_code: str
    def to_dict(self) -> dict[str, Any]:
        return {'file_path': self.file_path, 'source_code': self.source_code}

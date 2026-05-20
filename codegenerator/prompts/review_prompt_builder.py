from __future__ import annotations

import json
from typing import Any


def _compact_json(value: Any, *, limit: int = 0) -> str:
    text = json.dumps(value if value is not None else {}, ensure_ascii=False, indent=2)
    if limit and len(text) > limit:
        return text[:limit] + "\n# ... truncated ..."
    return text


def _compact_text(value: Any, *, limit: int = 0) -> str:
    text = str(value or "")
    if limit and len(text) > limit:
        return text[:limit] + "\n# ... truncated ..."
    return text


class GeneratedTestFailureReviewPromptBuilder:
    """Builds prompt for advisory review of generated-test-only failures."""

    def __init__(self, template: str) -> None:
        self.template = template

    def build(self, request: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        project_context = request.get("project_context") or {}
        verification_context = request.get("verification_context") or {}
        generated_test = request.get("generated_test") or {}
        production_artifact = request.get("production_artifact") or {}
        values = {
            "change_request_block": _compact_json(request.get("change_request") or {}, limit=2200),
            "target_block": _compact_json(request.get("target") or {}, limit=1600),
            "production_code_block": _compact_text(production_artifact.get("code") or "", limit=5500),
            "production_diff_block": _compact_text(production_artifact.get("diff") or "", limit=4500),
            "generated_test_block": _compact_text(generated_test.get("source_code") or "", limit=5500),
            "generated_test_path": _compact_text(generated_test.get("file_path") or "", limit=500),
            "verification_block": _compact_json(verification_context, limit=6000),
            "context_block": _compact_json(project_context, limit=5000),
        }
        prompt = self.template.format(**values)
        metrics = {
            "prompt_chars": len(prompt),
            "production_code_chars": len(str(production_artifact.get("code") or "")),
            "generated_test_chars": len(str(generated_test.get("source_code") or "")),
            "verification_context_chars": len(json.dumps(verification_context, ensure_ascii=False)),
        }
        return prompt, metrics

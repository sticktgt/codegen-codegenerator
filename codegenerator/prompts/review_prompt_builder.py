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


def _extract_target_source(project_context: dict[str, Any]) -> str:
    target_symbol = project_context.get("target_symbol") or project_context.get("target_function") or {}
    if isinstance(target_symbol, dict):
        return str(target_symbol.get("source") or "")
    return ""


def _extract_full_file_source(project_context: dict[str, Any]) -> str:
    return str(project_context.get("full_file_source") or "")


def _extract_review_visible_context(project_context: dict[str, Any]) -> dict[str, Any]:
    """Return a compact structured context for review without dumping huge source twice.

    The review model needs enough project context to judge whether production code
    likely preserved old behavior.  The raw old target/full file are rendered as
    separate blocks, so this summary intentionally keeps only compact structured
    facts.
    """
    if not isinstance(project_context, dict):
        return {}
    keys = (
        "available_imports",
        "model_surfaces",
        "contract_attribute_requirements",
        "verification_contract",
        "required_contracts",
        "preservation_guidance",
    )
    result: dict[str, Any] = {}
    for key in keys:
        value = project_context.get(key)
        if value:
            result[key] = value
    return result


class GeneratedTestFailureReviewPromptBuilder:
    """Builds prompt for advisory review of generated-test-only failures."""

    def __init__(self, template: str) -> None:
        self.template = template

    def build(self, request: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        project_context = request.get("project_context") or {}
        verification_context = request.get("verification_context") or {}
        generated_test = request.get("generated_test") or {}
        production_artifact = request.get("production_artifact") or {}
        old_target_source = _extract_target_source(project_context)
        full_file_source = _extract_full_file_source(project_context)
        visible_context = _extract_review_visible_context(project_context)
        values = {
            "change_request_block": _compact_json(request.get("change_request") or {}, limit=3200),
            "target_block": _compact_json(request.get("target") or {}, limit=1600),
            "old_target_source_block": _compact_text(old_target_source, limit=6000),
            "full_file_source_block": _compact_text(full_file_source, limit=16000),
            "production_code_block": _compact_text(production_artifact.get("code") or "", limit=7000),
            "production_diff_block": _compact_text(production_artifact.get("diff") or "", limit=7000),
            "generated_test_block": _compact_text(generated_test.get("source_code") or "", limit=7000),
            "generated_test_path": _compact_text(generated_test.get("file_path") or "", limit=500),
            "verification_block": _compact_json(verification_context, limit=9000),
            "context_block": _compact_json(visible_context, limit=7000),
        }
        prompt = self.template.format(**values)
        metrics = {
            "prompt_chars": len(prompt),
            "production_code_chars": len(str(production_artifact.get("code") or "")),
            "production_diff_chars": len(str(production_artifact.get("diff") or "")),
            "generated_test_chars": len(str(generated_test.get("source_code") or "")),
            "verification_context_chars": len(json.dumps(verification_context, ensure_ascii=False)),
            "review_old_target_source_chars": len(old_target_source),
            "review_full_file_source_chars": len(full_file_source),
            "review_visible_context_chars": len(json.dumps(visible_context, ensure_ascii=False)),
            "review_has_old_target_source": bool(old_target_source.strip()),
            "review_has_full_file_source": bool(full_file_source.strip()),
        }
        return prompt, metrics

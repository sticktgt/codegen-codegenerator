from __future__ import annotations
from codegenerator.parsing.response_parser import parse_llm_json, normalize_code_fields
from codegenerator.generation.coder import (
    _normalize_operation,
    CANONICAL_OPERATIONS,
    _normalize_import_changes,
    _normalize_insert_scope,
    _strip_leading_imports_for_insert_after,
    _normalize_expected_new_symbol_kind,
)


def parse_repair_response(content: str) -> dict:
    parsed = normalize_code_fields(parse_llm_json(content))
    if 'target_qualname' not in parsed and 'target_symbol' in parsed:
        parsed['target_qualname'] = parsed['target_symbol']
    missing=[k for k in ['target_file','operation','code'] if k not in parsed]
    if missing:
        raise ValueError(f"repair result is missing required keys: {', '.join(missing)}")
    parsed['operation'] = _normalize_operation(str(parsed['operation']))
    if parsed['operation'] not in CANONICAL_OPERATIONS:
        raise ValueError("repair result field 'operation' must be one of replace_symbol, add_symbol, insert_after_symbol")
    if parsed['operation'] == 'insert_after_symbol':
        parsed['code'] = _strip_leading_imports_for_insert_after(str(parsed.get('code') or ''))
    parsed['insert_scope'] = _normalize_insert_scope(parsed.get('insert_scope'))
    parsed['expected_new_symbol_kind'] = _normalize_expected_new_symbol_kind(parsed.get('expected_new_symbol_kind'))
    parsed['parent_qualname'] = str(parsed.get('parent_qualname') or '').strip() or None
    parsed['import_changes'] = _normalize_import_changes(parsed.get('import_changes'), code=str(parsed.get('code') or ''))
    return parsed


REPAIR_PLAN_REQUIRED_KEYS = {
    "status",
    "repair_objective",
    "allowed_calls_to_use",
    "forbidden_calls",
    "required_changes",
    "reason",
}

REPAIR_PLAN_CODE_ARTIFACT_KEYS = {
    "target_file",
    "target_symbol",
    "target_qualname",
    "operation",
    "code",
    "import_changes",
    "insert_scope",
    "expected_new_symbol_kind",
    "parent_qualname",
}


def parse_repair_plan_response(content: str) -> dict:
    parsed = parse_llm_json(content)
    if not isinstance(parsed, dict):
        raise ValueError("repair planner result must be a JSON object")

    keys = set(str(key) for key in parsed.keys())
    missing = sorted(REPAIR_PLAN_REQUIRED_KEYS - keys)
    extra = sorted(keys - REPAIR_PLAN_REQUIRED_KEYS)
    code_artifact_keys = sorted(keys & REPAIR_PLAN_CODE_ARTIFACT_KEYS)
    if missing or extra or code_artifact_keys:
        parts: list[str] = []
        if missing:
            parts.append(f"missing required keys: {', '.join(missing)}")
        if extra:
            parts.append(f"unexpected keys: {', '.join(extra)}")
        if code_artifact_keys:
            parts.append(
                "repair planner returned code-artifact keys instead of a plan: "
                + ", ".join(code_artifact_keys)
            )
        raise ValueError("repair planner result schema error: " + "; ".join(parts))

    status = str(parsed.get("status") or "").strip().lower()
    if status not in {"repairable", "not_repairable"}:
        raise ValueError("repair planner status must be repairable or not_repairable")
    parsed["status"] = status
    parsed["repair_objective"] = str(parsed.get("repair_objective") or "").strip()
    parsed["reason"] = str(parsed.get("reason") or "").strip()
    parsed["allowed_calls_to_use"] = _normalize_string_list_for_repair_plan(parsed.get("allowed_calls_to_use"))
    parsed["forbidden_calls"] = _normalize_string_list_for_repair_plan(parsed.get("forbidden_calls"))
    parsed["required_changes"] = _normalize_string_list_for_repair_plan(parsed.get("required_changes"))

    if status == "repairable" and not parsed["required_changes"]:
        raise ValueError("repair planner result schema error: repairable plan must include required_changes")
    if status == "repairable" and not parsed["repair_objective"]:
        raise ValueError("repair planner result schema error: repairable plan must include repair_objective")
    if not parsed["reason"]:
        raise ValueError("repair planner result schema error: reason must not be empty")

    return parsed


def _normalize_string_list_for_repair_plan(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        item = value.strip()
        return [item] if item else []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            text = str(item or "").strip()
            if text:
                result.append(text)
        return result
    text = str(value or "").strip()
    return [text] if text else []

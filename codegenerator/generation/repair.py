from __future__ import annotations
from codegenerator.parsing.response_parser import parse_llm_json, normalize_code_fields
from codegenerator.generation.coder import (
    _normalize_operation,
    CANONICAL_OPERATIONS,
    _normalize_import_changes,
    _strip_leading_imports_for_insert_after,
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
    parsed['insert_scope'] = str(parsed.get('insert_scope') or '').strip() or None
    parsed['expected_new_symbol_kind'] = str(parsed.get('expected_new_symbol_kind') or '').strip() or None
    parsed['parent_qualname'] = str(parsed.get('parent_qualname') or '').strip() or None
    parsed['import_changes'] = _normalize_import_changes(parsed.get('import_changes'))
    return parsed


def parse_repair_plan_response(content: str) -> dict:
    parsed = parse_llm_json(content)
    if not isinstance(parsed, dict):
        raise ValueError("repair planner result must be a JSON object")
    status = str(parsed.get("status") or "repairable").strip().lower()
    if status not in {"repairable", "not_repairable"}:
        raise ValueError("repair planner status must be repairable or not_repairable")
    parsed["status"] = status
    parsed["repair_objective"] = str(parsed.get("repair_objective") or "").strip()
    parsed["reason"] = str(parsed.get("reason") or parsed.get("message") or "").strip()
    parsed["allowed_calls_to_use"] = _normalize_string_list_for_repair_plan(parsed.get("allowed_calls_to_use"))
    parsed["forbidden_calls"] = _normalize_string_list_for_repair_plan(parsed.get("forbidden_calls"))
    parsed["required_changes"] = _normalize_string_list_for_repair_plan(parsed.get("required_changes"))
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

from __future__ import annotations
from typing import Any
from codegenerator.parsing.response_parser import parse_llm_json

CANONICAL_OPERATIONS = {"replace_symbol", "insert_after_symbol", "add_symbol"}


def _normalize_operation(operation: str) -> str:
    value = str(operation or '').strip().lower()
    mapping = {
        'replace_function': 'replace_symbol',
        'modify_function': 'replace_symbol',
        'replace_method': 'replace_symbol',
        'replace_symbol': 'replace_symbol',
        'insert_after_function': 'insert_after_symbol',
        'insert_after_symbol': 'insert_after_symbol',
        'add_function': 'add_symbol',
        'add_method': 'add_symbol',
        'add_symbol': 'add_symbol',
    }
    return mapping.get(value, value)

def validate_planner_result(parsed: dict[str, Any]) -> dict[str, Any]:
    required=['operation','target_file','target_symbol','intent_summary','constraints']
    missing=[k for k in required if k not in parsed]
    if missing:
        raise ValueError(f"planner result is missing required keys: {', '.join(missing)}")
    if not isinstance(parsed.get('constraints'), list):
        raise ValueError("planner result field 'constraints' must be a JSON array")

    parsed['operation'] = _normalize_operation(str(parsed.get('operation', '')))
    if parsed['operation'] not in CANONICAL_OPERATIONS:
        raise ValueError(
            "planner result field 'operation' must be one of "
            "replace_symbol, insert_after_symbol, add_symbol"
        )

    parsed.setdefault('reference_symbol', None)
    return parsed

def parse_planner_response(content: str) -> dict[str, Any]:
    return validate_planner_result(parse_llm_json(content))

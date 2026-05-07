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



def _normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            text = str(item or '').strip()
            if text:
                result.append(text)
        return result
    text = str(value or '').strip()
    return [text] if text else []

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
    parsed['constraints'] = _normalize_string_list(parsed.get('constraints'))
    parsed['explicit_requirements'] = _normalize_string_list(parsed.get('explicit_requirements'))
    parsed['preserve_literals'] = _normalize_string_list(parsed.get('preserve_literals'))
    return parsed

def parse_planner_response(content: str) -> dict[str, Any]:
    return validate_planner_result(parse_llm_json(content))

def validate_test_planner_result(parsed: dict[str, Any]) -> dict[str, Any]:
    required = ['target_symbol', 'test_intent', 'must_use_symbols', 'avoid']
    missing = [key for key in required if key not in parsed]
    if missing:
        raise ValueError(f"test planner result is missing required keys: {', '.join(missing)}")

    parsed['must_use_symbols'] = _normalize_string_list(parsed.get('must_use_symbols'))
    parsed['avoid'] = _normalize_string_list(parsed.get('avoid'))
    parsed['notes'] = _normalize_string_list(parsed.get('notes'))

    return parsed


def parse_test_planner_response(content: str) -> dict[str, Any]:
    return validate_test_planner_result(parse_llm_json(content))
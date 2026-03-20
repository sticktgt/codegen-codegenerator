from __future__ import annotations
from codegenerator.parsing.response_parser import parse_llm_json, normalize_code_fields

CANONICAL_OPERATIONS = {"replace_symbol", "add_symbol", "insert_after_symbol"}


def _normalize_operation(operation: str) -> str:
    value = str(operation or '').strip().lower()
    mapping = {
        'modify_function': 'replace_symbol',
        'replace_function': 'replace_symbol',
        'replace_method': 'replace_symbol',
        'replace_symbol': 'replace_symbol',
        'modify_symbol': 'replace_symbol',
        'add_function': 'add_symbol',
        'add_method': 'add_symbol',
        'add_symbol': 'add_symbol',
        'insert_after_function': 'insert_after_symbol',
        'insert_after_symbol': 'insert_after_symbol',
    }
    return mapping.get(value, value)


def parse_code_response(content: str) -> dict:
    parsed = normalize_code_fields(parse_llm_json(content))
    required=['target_file','operation','code']
    missing=[k for k in required if k not in parsed]
    if missing:
        raise ValueError(f"code result is missing required keys: {', '.join(missing)}")
    parsed['operation']=_normalize_operation(str(parsed['operation']))
    if parsed['operation'] not in CANONICAL_OPERATIONS:
        raise ValueError("code result field 'operation' must be one of replace_symbol, add_symbol, insert_after_symbol")
    return parsed

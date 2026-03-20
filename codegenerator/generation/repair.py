from __future__ import annotations
from codegenerator.parsing.response_parser import parse_llm_json, normalize_code_fields
from codegenerator.generation.coder import _normalize_operation, CANONICAL_OPERATIONS


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
    return parsed

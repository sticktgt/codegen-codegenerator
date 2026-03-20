from __future__ import annotations
from typing import Any
from codegenerator.parsing.response_parser import parse_llm_json

def validate_planner_result(parsed: dict[str, Any]) -> dict[str, Any]:
    required=['operation','target_file','target_symbol','intent_summary','constraints']
    missing=[k for k in required if k not in parsed]
    if missing:
        raise ValueError(f"planner result is missing required keys: {', '.join(missing)}")
    if not isinstance(parsed.get('constraints'), list):
        raise ValueError("planner result field 'constraints' must be a JSON array")
    parsed.setdefault('reference_symbol', None)
    return parsed

def parse_planner_response(content: str) -> dict[str, Any]:
    return validate_planner_result(parse_llm_json(content))

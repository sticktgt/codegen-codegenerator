from __future__ import annotations
from typing import Any
from codegenerator.parsing.response_parser import parse_llm_json

CANONICAL_OPERATIONS = {"replace_symbol", "insert_after_symbol", "add_symbol"}
PLANNER_DISALLOWED_CODE_ARTIFACT_KEYS = {
    "code",
    "import_changes",
    "test_file",
    "source_code",
    "target_qualname",
    "insert_after",
}


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


def _normalize_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or '').strip().lower()
    return text in {'true', '1', 'yes', 'да', 'required', 'обязательно'}


def _normalize_suggested_reuse(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    result: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            symbol = str(
                item.get('symbol')
                or item.get('name')
                or item.get('qualname')
                or item.get('reference_symbol')
                or ''
            ).strip()
            reason = str(item.get('reason') or item.get('usage') or item.get('why') or '').strip()
            required = _normalize_bool(item.get('required'))
        else:
            symbol = str(item or '').strip()
            reason = ''
            required = False
        if not symbol and not reason:
            continue
        result.append({'symbol': symbol, 'reason': reason, 'required': required})
    return result


def _fallback_intent_summary(parsed: dict[str, Any]) -> str:
    for key in ('intent_summary', 'summary', 'description', 'reason'):
        value = str(parsed.get(key) or '').strip()
        if value:
            return value
    target_symbol = str(parsed.get('target_symbol') or parsed.get('target_qualname') or '').strip()
    operation = str(parsed.get('operation') or '').strip()
    if target_symbol and operation:
        return f'Подготовить изменение {operation} для {target_symbol}'
    if target_symbol:
        return f'Подготовить изменение для {target_symbol}'
    return 'Подготовить изменение кода по запросу пользователя'


def validate_planner_result(parsed: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(parsed, dict):
        raise ValueError('planner result must be a JSON object')

    unexpected_artifact_keys = sorted(
        key for key in parsed if key in PLANNER_DISALLOWED_CODE_ARTIFACT_KEYS
    )
    if unexpected_artifact_keys:
        raise ValueError(
            'planner result must not contain code artifact keys: '
            + ', '.join(unexpected_artifact_keys)
        )

    status = str(parsed.get('status') or 'ok').strip().lower()
    if status not in {'ok', 'needs_planning', 'not_enough_context'}:
        status = 'ok'
    parsed['status'] = status

    if 'target_symbol' not in parsed and parsed.get('target_qualname'):
        parsed['target_symbol'] = parsed.get('target_qualname')

    if status in {'needs_planning', 'not_enough_context'}:
        parsed.setdefault('operation', _normalize_operation(str(parsed.get('operation') or 'insert_after_symbol')))
        parsed.setdefault('target_file', str(parsed.get('target_file') or ''))
        parsed.setdefault('target_symbol', str(parsed.get('target_symbol') or ''))
        parsed['intent_summary'] = _fallback_intent_summary(parsed)
        parsed['constraints'] = _normalize_string_list(parsed.get('constraints'))
        parsed.setdefault('reference_symbol', None)
        parsed.setdefault('insert_scope', None)
        parsed.setdefault('expected_new_symbol_kind', None)
        parsed.setdefault('parent_qualname', None)
        parsed['explicit_requirements'] = _normalize_string_list(parsed.get('explicit_requirements'))
        parsed['implementation_constraints'] = _normalize_string_list(parsed.get('implementation_constraints'))
        parsed['suggested_reuse'] = _normalize_suggested_reuse(parsed.get('suggested_reuse'))
        parsed['forbidden_assumptions'] = _normalize_string_list(parsed.get('forbidden_assumptions'))
        parsed['preserve_literals'] = _normalize_string_list(parsed.get('preserve_literals'))
        parsed.setdefault('reason', str(parsed.get('message') or parsed.get('reason') or status))
        parsed.setdefault('suggested_next_step', '')
        return parsed

    required = [
        'operation',
        'target_file',
        'target_symbol',
        'explicit_requirements',
        'implementation_constraints',
        'suggested_reuse',
        'forbidden_assumptions',
        'preserve_literals',
    ]
    missing = [key for key in required if key not in parsed]
    if missing:
        raise ValueError(f"planner result is missing required keys: {', '.join(missing)}")

    parsed['operation'] = _normalize_operation(str(parsed.get('operation', '')))
    if parsed['operation'] not in CANONICAL_OPERATIONS:
        raise ValueError(
            "planner result field 'operation' must be one of "
            "replace_symbol, insert_after_symbol, add_symbol"
        )

    parsed['intent_summary'] = _fallback_intent_summary(parsed)
    parsed['constraints'] = _normalize_string_list(parsed.get('constraints'))
    parsed.setdefault('reference_symbol', None)
    parsed.setdefault('insert_scope', None)
    parsed.setdefault('expected_new_symbol_kind', None)
    parsed.setdefault('parent_qualname', None)
    parsed['explicit_requirements'] = _normalize_string_list(parsed.get('explicit_requirements'))
    parsed['implementation_constraints'] = _normalize_string_list(parsed.get('implementation_constraints'))
    parsed['suggested_reuse'] = _normalize_suggested_reuse(parsed.get('suggested_reuse'))
    parsed['forbidden_assumptions'] = _normalize_string_list(parsed.get('forbidden_assumptions'))
    parsed['preserve_literals'] = _normalize_string_list(parsed.get('preserve_literals'))
    return parsed


def parse_planner_response(content: str) -> dict[str, Any]:
    return validate_planner_result(parse_llm_json(content))


def _fallback_test_intent(parsed: dict[str, Any]) -> str:
    for key in ('test_intent', 'intent_summary', 'summary', 'description', 'reason'):
        value = str(parsed.get(key) or '').strip()
        if value:
            return value
    target_symbol = str(
        parsed.get('target_symbol')
        or parsed.get('target_qualname')
        or parsed.get('tested_symbol')
        or parsed.get('symbol')
        or ''
    ).strip()
    if target_symbol:
        return f'Проверить поведение {target_symbol}'
    return 'Проверить сгенерированный Python-код по видимому проектному контексту'


def validate_test_planner_result(parsed: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(parsed, dict):
        raise ValueError('test planner result must be a JSON object')

    target_symbol = str(
        parsed.get('target_symbol')
        or parsed.get('target_qualname')
        or parsed.get('tested_symbol')
        or parsed.get('symbol')
        or ''
    ).strip()
    parsed['target_symbol'] = target_symbol
    parsed['test_intent'] = _fallback_test_intent(parsed)

    must_use_symbols = _normalize_string_list(
        parsed.get('must_use_symbols')
        or parsed.get('must_use')
        or parsed.get('symbols_to_use')
        or parsed.get('required_symbols')
    )
    if target_symbol and target_symbol not in must_use_symbols:
        must_use_symbols.insert(0, target_symbol)
    parsed['must_use_symbols'] = must_use_symbols

    avoid = _normalize_string_list(
        parsed.get('avoid')
        or parsed.get('forbidden')
        or parsed.get('avoid_symbols')
        or parsed.get('do_not_use')
    )
    for item in [
        'optional pytest plugin fixtures',
        'неимпортированные имена',
        '__dict__ без явного подтверждения контекста',
    ]:
        if item not in avoid:
            avoid.append(item)
    parsed['avoid'] = avoid
    parsed['notes'] = _normalize_string_list(parsed.get('notes'))

    return parsed


def parse_test_planner_response(content: str) -> dict[str, Any]:
    return validate_test_planner_result(parse_llm_json(content))

def validate_repair_planner_result(parsed: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(parsed, dict):
        raise ValueError('repair planner result must be a JSON object')

    required = ['status', 'repair_objective', 'allowed_calls_to_use', 'forbidden_calls', 'required_changes', 'reason']
    missing = [key for key in required if key not in parsed]
    typo_keys = [key for key in parsed if str(key).strip() != str(key) or key in {'forebidden_calls', 'forbidden_call'}]
    if missing or typo_keys:
        parts = []
        if missing:
            parts.append(f"missing required keys: {', '.join(missing)}")
        if typo_keys:
            parts.append(f"invalid keys: {', '.join(str(key) for key in typo_keys)}")
        raise ValueError('repair planner result schema error: ' + '; '.join(parts))

    status = str(parsed.get('status') or '').strip().lower()
    if status not in {'repairable', 'not_repairable'}:
        raise ValueError("repair planner result field 'status' must be repairable or not_repairable")
    parsed['status'] = status

    parsed['repair_objective'] = str(parsed.get('repair_objective') or '').strip()
    parsed['allowed_calls_to_use'] = _normalize_string_list(parsed.get('allowed_calls_to_use'))
    parsed['forbidden_calls'] = _normalize_string_list(parsed.get('forbidden_calls'))
    parsed['required_changes'] = _normalize_string_list(parsed.get('required_changes'))
    parsed['reason'] = str(parsed.get('reason') or '').strip()

    return parsed


def parse_repair_planner_response(content: str) -> dict[str, Any]:
    return validate_repair_planner_result(parse_llm_json(content))


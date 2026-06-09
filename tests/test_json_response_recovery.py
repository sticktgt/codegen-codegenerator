from __future__ import annotations

import pytest

from codegenerator.generation.repair import parse_repair_plan_response
from codegenerator.parsing.response_parser import parse_llm_json


def test_parse_llm_json_recovers_missing_final_object_brace() -> None:
    payload = '{"status":"ok","items":["a","b"]'

    parsed = parse_llm_json(payload)

    assert parsed == {"status": "ok", "items": ["a", "b"]}


def test_repair_plan_parser_recovers_truncated_valid_object() -> None:
    payload = (
        '{\n'
        '  "status": "repairable",\n'
        '  "repair_objective": "Исправить найденные ошибки",\n'
        '  "allowed_calls_to_use": ["visible.contract"],\n'
        '  "forbidden_calls": [],\n'
        '  "required_changes": ["Использовать видимый контракт"],\n'
        '  "reason": "Все значения завершены, но объект оборван после последнего поля"'
    )

    parsed = parse_repair_plan_response(payload)

    assert parsed["status"] == "repairable"
    assert parsed["required_changes"] == ["Использовать видимый контракт"]


def test_parse_llm_json_does_not_recover_unterminated_string() -> None:
    with pytest.raises(ValueError):
        parse_llm_json('{"status":"unterminated')


def test_repair_plan_parser_rejects_code_artifact_shape() -> None:
    payload = '{"target_file":"editor/window.py","operation":"replace_symbol","code":"def target():\\n    pass\\n"}'

    with pytest.raises(ValueError, match="code-artifact keys"):
        parse_repair_plan_response(payload)


def test_repair_plan_parser_requires_nonempty_repairable_changes() -> None:
    payload = (
        '{'
        '"status":"repairable",'
        '"repair_objective":"Исправить найденные ошибки",'
        '"allowed_calls_to_use":[],'
        '"forbidden_calls":[],'
        '"required_changes":[],'
        '"reason":"Есть исправление"'
        '}'
    )

    with pytest.raises(ValueError, match="required_changes"):
        parse_repair_plan_response(payload)

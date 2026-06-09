from __future__ import annotations

from pathlib import Path

import pytest

from codegenerator.generation.planner import parse_planner_response


ROOT = Path(__file__).resolve().parents[1]


def _read_prompt(name: str) -> str:
    return (ROOT / "prompts" / name).read_text(encoding="utf-8")


def test_planner_prompt_forbids_code_artifact_shape() -> None:
    prompt = _read_prompt("planner_user_template.txt")

    assert "JSON должен содержать только перечисленные поля верхнего уровня" in prompt
    assert "`code`" in prompt
    assert "`import_changes`" in prompt
    assert "другие поля code artifact" in prompt


def test_primary_coder_requires_visible_dependency_receiver_and_arg_type_check() -> None:
    prompt = _read_prompt("coder_user_template.txt")

    assert "точный receiver/access path" in prompt
    assert "Не создавай новый self-атрибут" in prompt
    assert "не оставляй несоответствие типа аргумента в надежде на последующий repair" in prompt
    assert "каждый `self.<attr>` должен быть видимым" in prompt


def test_repair_prompt_requires_required_changes_to_be_reflected_in_code() -> None:
    prompt = _read_prompt("repair_user_template.txt")

    assert "итоговый code должен явно реализовать каждое" in prompt
    assert "не должно оставлять исходную critical issue нерешенной" in prompt
    assert "точный видимый access path" in prompt


def test_planner_parser_rejects_code_artifact_keys() -> None:
    content = '''
    {
      "operation": "replace_symbol",
      "target_file": "pkg/mod.py",
      "target_symbol": "pkg.mod.fn",
      "intent_summary": "изменить функцию",
      "constraints": [],
      "reference_symbol": null,
      "insert_scope": "module_body",
      "expected_new_symbol_kind": "function",
      "parent_qualname": null,
      "explicit_requirements": [],
      "implementation_constraints": [],
      "suggested_reuse": [],
      "forbidden_assumptions": [],
      "preserve_literals": [],
      "code": "def fn(): pass"
    }
    '''
    with pytest.raises(ValueError, match="code artifact keys"):
        parse_planner_response(content)


def test_generated_test_prompts_forbid_parent_constructor_bypass_and_optional_plugin_fixtures() -> None:
    planner_prompt = _read_prompt("test_planner_user_template.txt")
    generator_prompt = _read_prompt("test_generator_user_template.txt")

    assert "Не планируй обход конструктора parent class через `__new__`" in planner_prompt
    assert "Не добавляй optional pytest plugin fixtures" in planner_prompt
    assert "Не используй `ParentClass.__new__(ParentClass)`" in generator_prompt
    assert "Не добавляй аргументы тестовой функции для optional pytest plugin fixtures" in generator_prompt
    assert "любая неизвестная fixture в сигнатуре теста является ошибкой генерации теста" in generator_prompt

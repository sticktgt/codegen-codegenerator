from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read_prompt(name: str) -> str:
    return (ROOT / "prompts" / name).read_text(encoding="utf-8")


def test_generated_test_prompts_warn_against_missing_module_patch_targets() -> None:
    planner = _read_prompt("test_planner_user_template.txt")
    generator = _read_prompt("test_generator_user_template.txt")

    assert "не видимое на уровне project-модуля" in planner
    assert "не записывай provider path" in planner
    assert "где имя реально разрешается" in generator
    assert "не импортирован или не определен на уровне этого модуля" in generator
    assert "локальный import внутри проверяемого symbol" in generator
    assert "target_module.ImportedName" in generator
    assert "Перед выбором monkeypatch/patch target" in generator


def test_code_prompts_require_import_changes_instead_of_local_imports() -> None:
    coder = _read_prompt("coder_user_template.txt")
    repair = _read_prompt("repair_user_template.txt")

    assert "Финальный artifact contract перед ответом" in coder
    assert "Не добавляй import-строки внутрь поля code" in coder
    assert "через import_changes" in coder
    assert "не рассчитывай, что импорт родительского модуля создаст вложенное имя" in coder
    assert "локальный import внутри target symbol" in repair
    assert "перенеси import в `import_changes`" in repair
    assert "Финальный artifact contract для repair" in repair


def test_generated_test_import_hints_are_not_must_use_symbols() -> None:
    planner = _read_prompt("test_planner_user_template.txt")
    generator = _read_prompt("test_generator_user_template.txt")

    assert "technical project imports" in planner
    assert "не список обязательных объектов теста" in planner
    assert "Не копируй symbols из этого блока в `must_use_symbols`" in planner
    assert "project storage/service class" in planner

    assert "technical project imports" in generator
    assert "не список объектов, которые нужно создать" in generator
    assert "не создавай настоящий экземпляр этого class" in generator
    assert "ParentClass.target_method(fake_self, ...)" in generator
    assert "не используй class-level вызовы для других project methods" in generator


def test_generated_test_review_prompt_distinguishes_exact_target_unbound_call() -> None:
    prompt = _read_prompt("generated_test_review_user_template.txt")

    assert "generated_test_calls_project_instance_method_on_class" in prompt
    assert "exact target method" in prompt
    assert "ParentClass.target_method(fake_self, ...)" in prompt
    assert "Для любых других project instance methods не рекомендуй class-level вызов" in prompt

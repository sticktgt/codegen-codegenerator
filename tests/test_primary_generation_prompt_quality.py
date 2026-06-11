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



def test_planner_prompt_requires_exact_json_shape_and_access_paths() -> None:
    prompt = _read_prompt("planner_user_template.txt")

    assert "Верни объект строго по этой форме" in prompt
    assert "Не пропускай `explicit_requirements`" in prompt
    assert "используй null для nullable-полей и [] для списков" in prompt
    assert "именно этот access path" in prompt
    assert "class/type-level form" in prompt


def test_primary_coder_distinguishes_owner_state_from_dependency_methods() -> None:
    prompt = _read_prompt("coder_user_template.txt")

    assert "`allowed_methods` в контексте означает список вызываемых методов" in prompt
    assert "не присваивай `self.<dependency>.<method_name> = ...`" in prompt
    assert "сначала ищи видимый атрибут на самом `self`" in prompt
    assert "не добавляй локальный import в тело target symbol" in prompt


def test_repair_prompt_forbids_extra_behavior_and_dependency_method_assignment() -> None:
    prompt = _read_prompt("repair_user_template.txt")

    assert "Исправляй только перечисленные critical issues" in prompt
    assert "не должен добавлять неподтвержденные дополнительные изменения" in prompt
    assert "Не исправляй unknown attribute путем присваивания" in prompt
    assert "перенеси его в `import_changes`" in prompt


def test_planner_prompt_template_renders_json_skeleton_without_format_keyerror() -> None:
    from codegenerator.models.requests import GenerationRequest
    from codegenerator.prompts.prompt_builder import build_planner_user_prompt

    template = _read_prompt("planner_user_template.txt")
    request = GenerationRequest(
        request_id="planner-template-render",
        mode="generate",
        change_request={
            "title": "Реализовать метод",
            "description": "Метод должен выполнить действие.",
            "constraints": [],
            "notes": [],
        },
        target={
            "qualname": "pkg.mod.Class.method",
            "file_path": "pkg/mod.py",
            "operation": "replace_symbol",
            "insert_scope": "class_body",
            "expected_new_symbol_kind": "method",
            "parent_qualname": "pkg.mod.Class",
        },
        project_context={
            "module_outline": [],
            "full_file_source": "",
            "target_symbol": {
                "qualname": "pkg.mod.Class.method",
                "name": "method",
                "kind": "method",
                "source": "def method(self):\n    pass\n",
            },
            "related_tests": [],
        },
    )

    prompt, metrics = build_planner_user_prompt(template, request)

    assert '"operation": "replace_symbol | insert_after_symbol"' in prompt
    assert '"explicit_requirements": []' in prompt
    assert metrics["planner_prompt_chars"] == len(prompt)


def test_coder_prompt_includes_compact_target_contract_block() -> None:
    from codegenerator.config import load_config
    from codegenerator.models.requests import GenerationRequest
    from codegenerator.prompts.prompt_builder import build_coder_user_prompt

    template = _read_prompt("coder_user_template.txt")
    config = load_config("config.yaml")
    request = GenerationRequest(
        request_id="compact-contract-coder",
        mode="generate",
        change_request={
            "title": "Открыть элемент",
            "description": "Загрузить элемент через существующее хранилище и обновить состояние окна.",
            "constraints": [],
        },
        target={
            "qualname": "app.window.Window.open_item",
            "file_path": "app/window.py",
            "operation": "replace_symbol",
            "insert_scope": "class_body",
        },
        project_context={
            "target_symbol": {
                "qualname": "app.window.Window.open_item",
                "name": "open_item",
                "kind": "method",
                "source": "def open_item(self):\n    raise NotImplementedError()\n",
            },
            "allowed_api_surface": {
                "dependencies": [
                    {
                        "access_path": "self.storage",
                        "type_name": "Storage",
                        "allowed_methods": [
                            {
                                "name": "load_from_file",
                                "signature": "def load_from_file(self, file_path: Path) -> Item:",
                            }
                        ],
                    },
                    {"access_path": "self.item", "type_name": "Item", "allowed_methods": []},
                ]
            },
            "module_outline": [],
            "related_tests": [],
        },
    )

    prompt, metrics = build_coder_user_prompt(template, request, {}, config)

    assert "Краткий контракт текущей задачи" in prompt
    assert "app.window.Window.open_item" in prompt
    assert "self.storage.load_from_file" in prompt
    assert "Path" in prompt
    assert "Проверка преобразований аргументов" in prompt
    assert "Не оставляй такое несоответствие на repair" in prompt
    assert "Финальный artifact contract перед ответом" in prompt
    assert "не заменяет пользовательский запрос" in prompt
    assert metrics["compact_target_contract_chars"] > 0


def test_repair_prompt_includes_compact_target_contract_and_russian_diagnostics() -> None:
    from codegenerator.config import load_config
    from codegenerator.models.requests import RepairRequest
    from codegenerator.prompts.prompt_builder import build_repair_user_prompt

    template = _read_prompt("repair_user_template.txt")
    config = load_config("config.yaml")
    request = RepairRequest(
        request_id="compact-contract-repair",
        mode="repair",
        previous_generation_request_id="generate-open",
        change_request={"title": "Открыть элемент", "description": "Загрузить элемент."},
        error_context={
            "verification_summary": {
                "failed_blocks": [
                    {
                        "name": "patch_static_semantics",
                        "details": {
                            "self_attribute_usage_check": {
                                "known_attributes": ["storage", "item"],
                                "known_methods": ["open_item"],
                                "unknown_attributes": [{"attribute": "item_storage"}],
                            }
                        },
                        "issues": [
                            {
                                "code": "unknown_self_attribute",
                                "message": "Неизвестный self-атрибут в production-коде: `self.item_storage`.",
                                "symbol": "app.window.Window.open_item",
                            }
                        ],
                    }
                ]
            }
        },
        previous_artifact={
            "operation": "replace_symbol",
            "target_qualname": "app.window.Window.open_item",
            "target_file": "app/window.py",
            "code": "def open_item(self):\n    return self.item_storage.load()\n",
        },
        project_context={
            "target_symbol": {
                "qualname": "app.window.Window.open_item",
                "name": "open_item",
                "kind": "method",
                "source": "def open_item(self):\n    raise NotImplementedError()\n",
            },
            "allowed_api_surface": {
                "dependencies": [
                    {
                        "access_path": "self.storage",
                        "type_name": "Storage",
                        "allowed_methods": [{"name": "load", "signature": "def load(self, key: str) -> Item:"}],
                    }
                ]
            },
        },
    )

    prompt = build_repair_user_prompt(template, request, config)

    assert "Краткий контракт текущей задачи" in prompt
    assert "Критические diagnostics для repair" in prompt
    assert "Финальный artifact contract для repair" in prompt
    assert "удали его из `code` и перенеси import в `import_changes`" in prompt
    assert "Полностью удали неизвестный self-атрибут" in prompt
    assert "Remove every use" not in prompt


def test_coder_prompt_request_block_deduplicates_constraints_after_compact_contract() -> None:
    from codegenerator.config import load_config
    from codegenerator.models.requests import GenerationRequest
    from codegenerator.prompts.prompt_builder import build_coder_user_prompt

    template = _read_prompt("coder_user_template.txt")
    config = load_config("config.yaml")
    request = GenerationRequest(
        request_id="dedupe-coder-prompt",
        mode="generate",
        change_request={
            "title": "Обновить метод",
            "description": "Метод должен обновить состояние.",
            "constraints": [
                "Не менять формат данных.",
                "Использовать существующее хранилище.",
                "Не добавлять внешние зависимости.",
            ],
        },
        target={
            "qualname": "app.window.Window.update_item",
            "file_path": "app/window.py",
            "operation": "replace_symbol",
            "insert_scope": "class_body",
        },
        project_context={
            "target_symbol": {
                "qualname": "app.window.Window.update_item",
                "name": "update_item",
                "kind": "method",
                "source": "def update_item(self):\n    raise NotImplementedError()\n",
            },
            "allowed_api_surface": {"dependencies": []},
            "module_outline": [],
            "related_tests": [],
        },
    )

    prompt, _ = build_coder_user_prompt(
        template,
        request,
        planner_result={
            "intent_summary": "обновить состояние",
            "explicit_requirements": ["обновить состояние"],
            "implementation_constraints": ["использовать видимый target"],
            "forbidden_assumptions": ["не добавлять новый сервис"],
        },
        runtime_config=config,
    )

    assert "Краткий контракт текущей задачи" in prompt
    assert "Не менять формат данных." in prompt
    assert prompt.count("- Не менять формат данных.") == 1
    assert "Требования пользователя из planner_json" not in prompt
    assert "Технические ограничения применения из planner_json" not in prompt
    assert "Запрещенные допущения из planner_json" not in prompt


def test_repair_prompt_does_not_duplicate_final_import_contract_tail() -> None:
    prompt = _read_prompt("repair_user_template.txt")

    assert prompt.count("Финальный artifact contract для repair") == 1
    assert prompt.count("Перед финальным ответом проверь") == 0
    assert prompt.count("Если repair planner или diagnostics требует добавить import") == 0

def test_final_artifact_contract_is_after_context_blocks() -> None:
    coder = _read_prompt("coder_user_template.txt")
    repair = _read_prompt("repair_user_template.txt")

    assert coder.rfind("Финальный artifact contract перед ответом") > coder.rfind("{reference_function_block}")
    assert repair.rfind("Финальный artifact contract для repair") > repair.rfind("{reference_context_block}")


def test_prompts_avoid_local_import_regression_without_growing_large_rules() -> None:
    coder = _read_prompt("coder_user_template.txt")
    repair = _read_prompt("repair_user_template.txt")
    repair_planner = _read_prompt("repair_planner_user_template.txt")

    assert "расширяй этот module через `add_from_import`" in coder
    assert "не используй локальный import" in coder
    assert "`alias` в `add_import` является alias модуля" in repair
    assert "required_changes не записывай Python import statements" in repair_planner
    assert "structured import_changes object" in repair_planner

def test_repair_planner_prompt_renders_structured_import_example() -> None:
    from codegenerator.config import load_config
    from codegenerator.models.requests import RepairRequest
    from codegenerator.prompts.prompt_builder import build_repair_planner_user_prompt

    template = _read_prompt("repair_planner_user_template.txt")
    config = load_config("config.yaml")
    request = RepairRequest(
        request_id="repair-planner-import-example",
        mode="repair",
        previous_generation_request_id="generate-open",
        change_request={
            "title": "Открыть файл",
            "description": "Исправить загрузку файла.",
            "constraints": [],
            "notes": [],
        },
        error_context={
            "verification_summary": {
                "failed_blocks": [
                    {
                        "name": "patch_static_semantics",
                        "issues": [
                            {
                                "code": "unknown_runtime_name",
                                "message": "Нужно добавить import.",
                                "symbol": "app.window.Window.open_item",
                                "unknown_names": ["Dialog"],
                            }
                        ],
                    }
                ]
            }
        },
        previous_artifact={
            "operation": "replace_symbol",
            "target_file": "app/window.py",
            "target_qualname": "app.window.Window.open_item",
            "code": "def open_item(self):\n    Dialog.open()\n",
        },
        project_context={
            "target_symbol": {
                "qualname": "app.window.Window.open_item",
                "name": "open_item",
                "kind": "method",
                "source": "def open_item(self):\n    pass\n",
            },
            "module_outline": [],
            "allowed_api_surface": {"dependencies": []},
        },
        target={"file_path": "app/window.py", "qualname": "app.window.Window.open_item"},
    )

    prompt = build_repair_planner_user_prompt(template, request, runtime_config=config)

    assert '{{"action"' not in prompt
    assert '{"action": "add_from_import", "module": "package.module", "names": ["Name"]}' in prompt
    assert "required_changes не записывай Python import statements" in prompt



def test_test_generator_final_contract_prevents_heavy_parent_and_unknown_model_methods() -> None:
    prompt = _read_prompt("test_generator_user_template.txt")

    assert "Финальная проверка generated test перед ответом" in prompt
    assert "ParentClass.target_method(fake_self, ...)" in prompt
    assert "не создавай `ParentClass()`" in prompt
    assert "не запускай UI/application/event loop" in prompt
    assert "не создавай настоящий storage/service/controller" in prompt
    assert "Не вызывай методы, которых нет в visible method list" in prompt
    assert prompt.rfind("Финальная проверка generated test перед ответом") > prompt.rfind("{full_file_source_block}")


def test_test_planner_final_contract_filters_technical_must_use_symbols() -> None:
    prompt = _read_prompt("test_planner_user_template.txt")

    assert "Финальная проверка плана generated test" in prompt
    assert "Не включай parent class в `must_use_symbols`" in prompt
    assert "Не включай project storage/service class в `must_use_symbols`" in prompt
    assert "Не планируй настоящий parent instance" in prompt

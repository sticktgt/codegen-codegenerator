from pathlib import Path


def test_coder_and_repair_prompts_use_general_import_completeness_rules() -> None:
    root = Path(__file__).resolve().parents[1]
    coder = (root / 'prompts' / 'coder_user_template.txt').read_text(encoding='utf-8')
    repair = (root / 'prompts' / 'repair_user_template.txt').read_text(encoding='utf-8')

    for template in (coder, repair):
        assert 'external/module-level имя' in template
        assert 'Форма import_changes должна соответствовать форме использования имени в code' in template
        assert 'Не вводи новые import aliases без явной причины' in template
        assert 'Path(...)' not in template
        assert 'Path as Path_' not in template
        assert 'module": "pathlib"' not in template


def test_coder_prompt_does_not_duplicate_allowed_api_surface_rule() -> None:
    root = Path(__file__).resolve().parents[1]
    coder = (root / 'prompts' / 'coder_user_template.txt').read_text(encoding='utf-8')

    duplicate_phrase = 'Если Allowed API Surface передан в контексте, любые вызовы методов зависимостей должны совпадать'
    assert duplicate_phrase not in coder
    assert coder.count('Allowed API Surface') <= 5


def test_coder_and_repair_prompts_require_structured_import_changes_objects() -> None:
    root = Path(__file__).resolve().parents[1]
    coder = (root / 'prompts' / 'coder_user_template.txt').read_text(encoding='utf-8')
    repair = (root / 'prompts' / 'repair_user_template.txt').read_text(encoding='utf-8')

    for template in (coder, repair):
        assert 'Каждый элемент import_changes должен быть JSON-объектом' in template
        assert 'Не возвращай import_changes вида ["from package.module import Name"]' in template
        assert '{"action": "add_from_import", "module": "package.module", "names": ["Name"]}' in template

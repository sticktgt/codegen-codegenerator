from __future__ import annotations

from pathlib import Path


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_generated_test_auto_fix_is_not_exposed_in_cli_or_config() -> None:
    root = _root()
    checked_files = [
        root / 'codegenerator' / 'api' / 'cli.py',
        root / 'codegenerator' / 'api' / 'service.py',
        root / 'config.yaml',
    ]
    combined = '\n'.join(path.read_text(encoding='utf-8') for path in checked_files)

    assert 'repair-generated-test' not in combined
    assert 'repair_generated_test_from_file' not in combined
    assert 'test_repair_enabled' not in combined


def test_generated_test_review_prompt_is_advisory_only() -> None:
    template = (_root() / 'prompts' / 'generated_test_review_user_template.txt').read_text(encoding='utf-8')

    assert 'recommended_action' in template
    assert 'production_risks' in template
    assert 'test_issues' in template
    assert 'generated_test_repair' not in template


def test_generated_test_prompts_require_direct_target_invocation() -> None:
    root = _root()
    planner_template = (root / 'prompts' / 'test_planner_user_template.txt').read_text(encoding='utf-8')
    generator_template = (root / 'prompts' / 'test_generator_user_template.txt').read_text(encoding='utf-8')

    assert 'прямой вызов target symbol' in planner_template
    assert 'локальную копию' in planner_template
    assert 'вызывать проверяемый target symbol напрямую' in generator_template
    assert 'fake/stub должны быть только окружением target-вызова' in generator_template


def test_repair_planner_prompt_rejects_code_artifact_shape_and_requires_minimal_scope() -> None:
    template = (_root() / 'prompts' / 'repair_planner_user_template.txt').read_text(encoding='utf-8')

    assert 'Это только план repair' in template
    assert 'Не возвращай ключи `target_file`' in template
    assert 'Планируй минимальное исправление только для перечисленных critical issues' in template
    assert 'не меняй сам project contract, receiver вызова' in template


def test_generated_test_prompt_prefers_fake_dependencies_over_real_project_setup() -> None:
    template = (_root() / 'prompts' / 'test_generator_user_template.txt').read_text(encoding='utf-8')

    assert 'создай минимальный fake dependency' in template
    assert 'Не создавай настоящий project dependency' in template
    assert 'Если `test_plan.avoid` запрещает symbol/API' in template

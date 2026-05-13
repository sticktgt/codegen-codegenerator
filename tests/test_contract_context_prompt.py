from __future__ import annotations

from pathlib import Path
from dataclasses import asdict

from codegenerator.config import load_config
from codegenerator.context.budget import apply_budget_strategy
from codegenerator.models.requests import GenerationRequest
from codegenerator.prompts.prompt_builder import build_coder_user_prompt


def _request() -> GenerationRequest:
    return GenerationRequest(
        request_id='req-contract-context',
        mode='generate',
        change_request={
            'title': 'Добавить API endpoint',
            'description': 'Endpoint должен использовать существующую функцию create_ticket.',
            'constraints': [],
            'notes': [],
        },
        target={
            'qualname': 'support_app.api.ticket_api.create_ticket_endpoint',
            'file_path': 'support_app/api/ticket_api.py',
            'operation': 'replace_symbol',
            'insert_scope': None,
            'expected_new_symbol_kind': '',
            'parent_qualname': '',
        },
        project_context={
            'module_outline': [],
            'full_file_source': '',
            'target_symbol': {
                'qualname': 'support_app.api.ticket_api.create_ticket_endpoint',
                'name': 'create_ticket_endpoint',
                'kind': 'function',
                'source': 'def create_ticket_endpoint(payload):\n    return payload\n',
            },
            'related_tests': [],
            'contract_context': {
                'related_symbols': [
                    {
                        'qualname': 'support_app.services.ticket_service.create_ticket',
                        'file_path': 'support_app/services/ticket_service.py',
                        'kind': 'function',
                        'role': 'called_by_target',
                        'relation_kind': 'calls',
                        'relation_direction': 'outbound',
                        'relation_confidence': 'high',
                        'signature': 'def create_ticket(payload):',
                        'source_excerpt': 'def create_ticket(payload):\n    return {"id": payload["id"]}\n',
                    }
                ],
                'previous_changes': [],
            },
        },
    )


def test_coder_prompt_includes_contract_context() -> None:
    template = Path('prompts/coder_user_template.txt').read_text(encoding='utf-8')
    config = load_config('config.yaml')
    prompt, metrics = build_coder_user_prompt(
        template,
        _request(),
        planner_result={'explicit_requirements': ['использовать create_ticket']},
        runtime_config=config,
        available_user_chars=14000,
    )

    assert 'Связанные production-контракты' in prompt
    assert 'support_app.services.ticket_service.create_ticket' in prompt
    assert 'def create_ticket(payload):' in prompt
    assert metrics['contract_symbols_count'] == 1
    assert metrics['coder_contract_context_chars'] > 0


def test_budget_strategy_trims_contract_context() -> None:
    config = load_config('config.yaml')
    payload = asdict(_request())
    payload['project_context'] = dict(payload['project_context'])
    payload['project_context']['contract_context'] = {
        'related_symbols': [
            {
                'qualname': f'module.symbol_{index}',
                'source_excerpt': 'x' * 1000,
            }
            for index in range(5)
        ],
        'previous_changes': [],
    }

    trimmed, trim_log = apply_budget_strategy(
        payload,
        mode='generate',
        request_chars_limit=1200,
        logger=__import__('logging').getLogger(__name__),
        config=config,
    )

    related = trimmed['project_context']['contract_context']['related_symbols']
    assert len(related) <= config.coder_max_contract_symbols
    assert all(len(item.get('source_excerpt', '')) <= config.coder_max_contract_symbol_chars + 40 for item in related)
    assert any('related_symbols' in item for item in trim_log)

from codegenerator.generation.repair import parse_repair_response
from codegenerator.prompts.prompt_builder import build_test_generator_user_prompt, build_test_planner_user_prompt


def test_contract_context_prompt_renders_origin_qualname() -> None:
    template = Path('prompts/coder_user_template.txt').read_text(encoding='utf-8')
    config = load_config('config.yaml')
    request = _request()
    request.project_context['contract_context']['related_symbols'][0]['origin_qualname'] = (
        'support_app.api.controllers.TicketController.agent_summary_endpoint'
    )

    prompt, _ = build_coder_user_prompt(
        template,
        request,
        planner_result={'explicit_requirements': ['использовать create_ticket']},
        runtime_config=config,
        available_user_chars=14000,
    )

    assert 'Origin: support_app.api.controllers.TicketController.agent_summary_endpoint' in prompt


def test_repair_parser_dedents_insert_after_code() -> None:
    parsed = parse_repair_response(
        '{'
        '"target_file":"support_app/api/controllers.py",'
        '"operation":"insert_after_symbol",'
        '"code":"    def ticket_statistics_endpoint(self) -> dict:\\n        return {}"'
        '}'
    )

    assert parsed['code'].startswith('def ticket_statistics_endpoint')


def test_test_generation_prompts_disallow_pytest_mock() -> None:
    config = load_config('config.yaml')
    request = _request()
    planner_template = Path('prompts/test_planner_user_template.txt').read_text(encoding='utf-8')
    generator_template = Path('prompts/test_generator_user_template.txt').read_text(encoding='utf-8')

    planner_prompt, _ = build_test_planner_user_prompt(
        planner_template,
        request,
        runtime_config=config,
        generated_code_artifact={},
        available_user_chars=14000,
    )
    test_prompt, _ = build_test_generator_user_prompt(
        generator_template,
        request,
        generated_test_file='tests/test_generated.py',
        example_test_source='',
        runtime_config=config,
        available_user_chars=14000,
        generated_code_artifact={},
        test_plan={'target_symbol': 'support_app.api.ticket_api.create_ticket_endpoint'},
    )

    assert 'optional pytest plugin fixtures' in planner_prompt
    assert 'test-функции без fixture-параметров' in planner_prompt
    assert 'pytest-mock' not in planner_prompt
    assert 'mocker' not in planner_prompt
    assert 'optional pytest plugin fixtures' in test_prompt
    assert 'test-функции без fixture-параметров' in test_prompt
    assert 'pytest-mock' not in test_prompt
    assert 'mocker' not in test_prompt



def test_test_generator_prompt_filters_avoid_list_from_test_plan() -> None:
    config = load_config('config.yaml')
    request = _request()
    template = Path('prompts/test_generator_user_template.txt').read_text(encoding='utf-8')

    prompt, _ = build_test_generator_user_prompt(
        template,
        request,
        generated_test_file='tests/test_generated.py',
        example_test_source='',
        runtime_config=config,
        available_user_chars=14000,
        generated_code_artifact={},
        test_plan={
            'target_symbol': 'support_app.api.ticket_api.create_ticket_endpoint',
            'test_intent': 'Проверить endpoint',
            'must_use_symbols': ['support_app.api.ticket_api.create_ticket_endpoint'],
            'avoid': ['mocker', 'pytest-mock'],
        },
    )

    assert 'Проверить endpoint' in prompt
    assert 'support_app.api.ticket_api.create_ticket_endpoint' in prompt
    assert 'mocker' not in prompt
    assert 'pytest-mock' not in prompt


from codegenerator.generation.planner import parse_planner_response


def test_planner_parser_accepts_coder_shaped_plan_without_optional_summary_fields() -> None:
    parsed = parse_planner_response(
        '{'
        '"target_file":"support_app/api/controllers.py",'
        '"target_symbol":"support_app.api.controllers.TicketController",'
        '"operation":"insert_after_symbol",'
        '"insert_scope":"class_body",'
        '"code":"def endpoint(self):\\n    return None"'
        '}'
    )

    assert parsed['operation'] == 'insert_after_symbol'
    assert parsed['target_symbol'] == 'support_app.api.controllers.TicketController'
    assert parsed['intent_summary']
    assert parsed['constraints'] == []
    assert parsed['explicit_requirements'] == []
    assert parsed['preserve_literals'] == []



def test_contract_context_prompts_warn_about_required_arguments() -> None:
    coder_template = Path('prompts/coder_user_template.txt').read_text(encoding='utf-8')
    repair_template = Path('prompts/repair_user_template.txt').read_text(encoding='utf-8')
    test_planner_template = Path('prompts/test_planner_user_template.txt').read_text(encoding='utf-8')
    test_generator_template = Path('prompts/test_generator_user_template.txt').read_text(encoding='utf-8')

    assert 'не опускай обязательные аргументы' in coder_template
    assert 'нарушение сигнатуры связанного production-контракта' in repair_template
    assert 'меньшим числом обязательных аргументов' in test_planner_template
    assert 'без обязательных аргументов' in test_generator_template


def test_generation_prompts_warn_about_duplicate_insert_symbol_names() -> None:
    coder_template = Path('prompts/coder_user_template.txt').read_text(encoding='utf-8')
    repair_template = Path('prompts/repair_user_template.txt').read_text(encoding='utf-8')

    assert 'уникальным именем' in coder_template
    assert 'не используй имя уже существующего' in coder_template
    assert 'дубликат symbol' in repair_template
    assert 'не возвращай этот же symbol повторно' in repair_template


def test_coder_prompt_filters_planner_existing_symbol_name_for_insert_after() -> None:
    template = Path('prompts/coder_user_template.txt').read_text(encoding='utf-8')
    config = load_config('config.yaml')
    request = _request()
    request.target.update({
        'operation': 'insert_after_symbol',
        'insert_scope': 'class_body',
        'expected_new_symbol_kind': 'method',
        'parent_qualname': 'support_app.api.controllers.TicketController',
        'qualname': 'support_app.api.controllers.TicketController',
        'file_path': 'support_app/api/controllers.py',
    })
    request.change_request = {
        'title': 'Добавить API-функцию для получения статистики',
        'description': 'Добавь новый API-метод для получения статистики.',
        'constraints': [],
        'notes': [],
    }
    request.project_context['module_outline'] = [
        {'qualname': 'support_app.api.controllers.TicketController.agent_summary_endpoint', 'name': 'agent_summary_endpoint', 'kind': 'method'},
        {'qualname': 'support_app.api.controllers.TicketController.assign_ticket_endpoint', 'name': 'assign_ticket_endpoint', 'kind': 'method'},
    ]
    request.project_context['class_members'] = [
        {'qualname': 'support_app.api.controllers.TicketController.agent_summary_endpoint', 'name': 'agent_summary_endpoint', 'kind': 'method'},
    ]
    request.project_context['target_symbol'] = {
        'qualname': 'support_app.api.controllers.TicketController',
        'name': 'TicketController',
        'kind': 'class',
        'source': 'class TicketController:\n    def agent_summary_endpoint(self, agent_name: str) -> dict:\n        return {}\n',
    }

    prompt, _ = build_coder_user_prompt(
        template,
        request,
        planner_result={
            'operation': 'insert_after_symbol',
            'intent_summary': 'Добавить метод agent_summary_endpoint для статистики',
            'explicit_requirements': ['Добавить метод agent_summary_endpoint', 'Возвращать dict'],
            'preserve_literals': ['agent_summary_endpoint'],
            'constraints': ['Сохранить стиль'],
        },
        runtime_config=config,
        available_user_chars=14000,
    )

    assert 'Добавить метод agent_summary_endpoint' not in prompt
    assert 'User-specified names, signatures and literals to preserve exactly:\n- agent_summary_endpoint' not in prompt
    assert 'Создать новый symbol с уникальным именем' in prompt
    assert 'Возвращать dict' in prompt

from codegenerator.generation.test_generator import parse_test_response


def test_test_response_parser_keeps_code_without_policy_rewrite() -> None:
    payload = (
        '{'
        '"test_file":"tests/test_generated.py",'
        '"code":"def test_generated(mocker):\\n    assert True"'
        '}'
    )

    parsed = parse_test_response(payload, 'tests/test_generated.py')
    assert 'mocker' in parsed['code']
    assert 'def test_generated(mocker)' in parsed['code']


def test_test_response_parser_accepts_unittest_mock_import() -> None:
    payload = (
        '{'
        '"test_file":"tests/test_generated.py",'
        '"code":"from unittest.mock import MagicMock\\n\\ndef test_generated():\\n    mock = MagicMock()\\n    assert mock is not None"'
        '}'
    )

    parsed = parse_test_response(payload, 'tests/test_generated.py')
    assert 'MagicMock' in parsed['code']


def test_test_generation_prompt_prefers_fakes_over_mocker() -> None:
    planner_template = Path('prompts/test_planner_user_template.txt').read_text(encoding='utf-8')
    generator_template = Path('prompts/test_generator_user_template.txt').read_text(encoding='utf-8')

    assert 'optional pytest plugin fixtures' in planner_template
    assert 'fake/stub' in planner_template
    assert 'optional pytest plugin fixtures' in generator_template
    assert 'fake/stub' in generator_template


def test_test_generator_prompt_requires_project_names_to_be_imported_or_defined() -> None:
    from pathlib import Path

    template = Path('prompts/test_generator_user_template.txt').read_text(encoding='utf-8')
    assert 'не используй неимпортированные имена' in template
    assert 'явно импортирован из видимого project module' in template


def test_coder_prompt_rejects_placeholder_literals_for_contract_args() -> None:
    from pathlib import Path

    template = Path('prompts/coder_user_template.txt').read_text(encoding='utf-8')
    assert 'литерал-заглушку' in template
    assert 'измени сигнатуру нового symbol' in template


def test_repair_prompt_rejects_placeholder_literals_for_contract_args() -> None:
    from pathlib import Path

    template = Path('prompts/repair_user_template.txt').read_text(encoding='utf-8')
    assert 'литерал-заглушку' in template
    assert 'измени сигнатуру нового symbol' in template


def test_coder_prompt_prefers_visible_calling_pattern_over_fake_literals() -> None:
    from pathlib import Path

    template = Path('prompts/coder_user_template.txt').read_text(encoding='utf-8')
    assert 'видимый calling pattern' in template
    assert 'фиктивными константами' in template


def test_repair_prompt_prefers_visible_calling_pattern_over_fake_literals() -> None:
    from pathlib import Path

    template = Path('prompts/repair_user_template.txt').read_text(encoding='utf-8')
    assert 'видимый calling pattern' in template
    assert 'фиктивными константами' in template


def test_repair_prompt_includes_problem_block_placeholder() -> None:
    from pathlib import Path

    template = Path('prompts/repair_user_template.txt').read_text(encoding='utf-8')
    assert '{repair_problem_block}' in template


def test_repair_problem_block_mentions_contract_placeholder_objective() -> None:
    from codegenerator.prompts.prompt_builder import _build_repair_problem_block

    block = _build_repair_problem_block(
        {
            'verification_summary': {
                'failed_blocks': [
                    {
                        'name': 'patch_static_semantics',
                        'issues': [
                            {
                                'code': 'contract_call_uses_unrequested_literal_arg',
                                'message': "build_agent_summary uses literal 'all'",
                                'symbol': 'pkg.Controller',
                            }
                        ],
                    }
                ]
            }
        }
    )

    assert 'Критическая ошибка для repair' in block
    assert 'placeholder literal' in block
    assert 'build_agent_summary' in block

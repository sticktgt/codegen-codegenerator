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
                'source_excerpt': 'x' * 3000,
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


def test_test_generation_prompts_include_required_project_imports_from_model_surfaces() -> None:
    config = load_config('config.yaml')
    request = _request()
    request.change_request = {
        'title': 'Полнотекстовый поиск с результатами',
        'description': 'Новый метод должен возвращать SearchResult.',
        'constraints': [
            'Создавать SearchResult только с видимыми аргументами note, preview и match_positions.',
        ],
        'notes': [],
    }
    request.project_context['model_surfaces'] = [
        {
            'name': 'SearchResult',
            'qualname': 'note.note_search.SearchResult',
            'constructor_fields': ['note', 'preview', 'match_positions'],
            'fields': ['note', 'preview', 'match_positions'],
        }
    ]
    request.project_context['contract_context']['related_symbols'] = [
        {
            'qualname': 'note.note_search.build_context_fragment',
            'file_path': 'note/note_search.py',
            'kind': 'function',
            'role': 'required_reuse_contract',
            'signature': 'def build_context_fragment(text: str, query: str, max_length: int = 50) -> str:',
            'source_excerpt': 'def build_context_fragment(text, query, max_length=50):\n    return text[:max_length]\n',
        },
        {
            'qualname': 'note.note_search.find_match_positions',
            'file_path': 'note/note_search.py',
            'kind': 'function',
            'role': 'required_reuse_contract',
            'signature': 'def find_match_positions(text: str, query: str) -> list[int]:',
            'source_excerpt': 'def find_match_positions(text, query):\n    return []\n',
        },
    ]
    planner_template = Path('prompts/test_planner_user_template.txt').read_text(encoding='utf-8')
    generator_template = Path('prompts/test_generator_user_template.txt').read_text(encoding='utf-8')

    planner_prompt, _ = build_test_planner_user_prompt(
        planner_template,
        request,
        runtime_config=config,
        generated_code_artifact={
            'code': 'def search_results_by_content(self, query):\n    return [SearchResult(note=None, preview="", match_positions=[])]\n',
        },
        available_user_chars=30000,
    )
    generator_prompt, _ = build_test_generator_user_prompt(
        generator_template,
        request,
        generated_test_file='tests/test_generated.py',
        example_test_source='',
        runtime_config=config,
        available_user_chars=30000,
        generated_code_artifact={
            'code': 'def search_results_by_content(self, query):\n    return [SearchResult(note=None, preview="", match_positions=[])]\n',
        },
        test_plan={'must_use_symbols': ['note.note_search.SearchResult']},
    )

    expected_import = 'from note.note_search import SearchResult, build_context_fragment, find_match_positions'
    assert 'Required project imports' in planner_prompt
    assert expected_import in planner_prompt
    assert 'Required project imports' in generator_prompt
    assert expected_import in generator_prompt
    assert 'Не создавай экземпляр project class через `__new__`' in generator_prompt
    assert 'Не вызывай методы project object, которых нет' in generator_prompt


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


def test_required_project_imports_for_test_prompt_does_not_import_class_methods_as_top_level_functions():
    from codegenerator.models.requests import GenerationRequest
    from codegenerator.config import load_config
    from codegenerator.prompts.prompt_builder import build_test_generator_user_prompt

    template = '{required_imports_block}'
    request = GenerationRequest(
        request_id='test',
        mode='generate_test',
        change_request={
            'title': 'Добавить метод поиска',
            'description': 'Метод должен использовать search_by_content и возвращать SearchResult.',
            'constraints': [],
        },
        target={
            'qualname': 'note.note_storage.NoteStorage',
            'file_path': 'note/note_storage.py',
            'operation': 'insert_after_symbol',
            'insert_scope': 'class_body',
            'expected_new_symbol_kind': 'method',
            'parent_qualname': 'note.note_storage.NoteStorage',
        },
        project_context={
            'contract_context': {
                'related_symbols': [
                    {
                        'kind': 'class',
                        'name': 'NoteStorage',
                        'qualname': 'note.note_storage.NoteStorage',
                        'module_name': 'note.note_storage',
                    },
                    {
                        'kind': 'method',
                        'name': 'search_by_content',
                        'qualname': 'note.note_storage.NoteStorage.search_by_content',
                        'parent_qualname': 'note.note_storage.NoteStorage',
                        'module_name': 'note.note_storage',
                        'role': 'required_reuse_contract',
                    },
                    {
                        'kind': 'class',
                        'name': 'SearchResult',
                        'qualname': 'note.note_search.SearchResult',
                        'module_name': 'note.note_search',
                    },
                ]
            },
            'model_surfaces': [
                {
                    'name': 'SearchResult',
                    'qualname': 'note.note_search.SearchResult',
                    'constructor_fields': ['note', 'preview', 'match_positions'],
                }
            ],
        },
        options={},
    )

    prompt, _ = build_test_generator_user_prompt(
        template,
        request,
        generated_test_file='tests/test_generated.py',
        example_test_source='',
        runtime_config=load_config(),
        available_user_chars=20000,
        generated_code_artifact={
            'code': 'def search_results_by_content(self, query):\n    return []',
            'insert_scope': 'class_body',
            'expected_new_symbol_kind': 'method',
            'target_qualname': 'note.note_storage.NoteStorage',
        },
        test_plan={
            'must_use_symbols': [
                'note.note_storage.NoteStorage.search_results_by_content',
                'note.note_storage.NoteStorage.search_by_content',
                'note.note_search.SearchResult',
            ]
        },
    )

    assert 'from note.note_storage import NoteStorage' in prompt
    assert 'search_by_content' not in prompt.split('from note.note_storage import', 1)[1].split('\n', 1)[0]
    assert 'from note.note_search import SearchResult' in prompt


def test_production_required_imports_do_not_import_class_methods_from_contract_context() -> None:
    from pathlib import Path
    from codegenerator.config import load_config
    from codegenerator.prompts.prompt_builder import build_coder_user_prompt

    template = Path('prompts/coder_user_template.txt').read_text(encoding='utf-8')
    config = load_config('config.yaml')
    request = _request()
    request.change_request = {
        'title': 'Добавить метод поиска',
        'description': 'Метод должен использовать search_by_content и возвращать SearchResult.',
        'constraints': [],
        'notes': [],
    }
    request.project_context['required_contracts'] = [
        {
            'name': 'build_context_fragment',
            'qualname': 'note.note_search.build_context_fragment',
            'signature': 'def build_context_fragment(text: str, query: str, max_length: int = 50) -> str:',
        }
    ]
    request.project_context['contract_context']['related_symbols'] = [
        {
            'kind': 'method',
            'name': 'search_by_content',
            'qualname': 'note.note_storage.NoteStorage.search_by_content',
            'parent_qualname': 'note.note_storage.NoteStorage',
            'module_name': 'note.note_storage',
            'role': 'required_reuse_contract',
        },
        {
            'kind': 'function',
            'name': 'build_context_fragment',
            'qualname': 'note.note_search.build_context_fragment',
            'module_name': 'note.note_search',
            'role': 'required_reuse_contract',
        },
    ]
    request.project_context['model_surfaces'] = [
        {
            'name': 'SearchResult',
            'qualname': 'note.note_search.SearchResult',
            'constructor_fields': ['note', 'preview', 'match_positions'],
        }
    ]

    prompt, _ = build_coder_user_prompt(
        template,
        request,
        planner_result={'explicit_requirements': ['использовать search_by_content']},
        runtime_config=config,
        available_user_chars=30000,
    )

    assert 'from note.note_search import SearchResult, build_context_fragment' in prompt
    assert 'from note.note_storage import search_by_content' not in prompt
    assert 'from note.note_storage import NoteStorage' not in prompt


def test_repair_prompt_renders_required_import_changes_for_unknown_names() -> None:
    from pathlib import Path
    from codegenerator.config import load_config
    from codegenerator.models.requests import RepairRequest
    from codegenerator.prompts.prompt_builder import build_repair_user_prompt

    template = Path('prompts/repair_user_template.txt').read_text(encoding='utf-8')
    config = load_config('config.yaml')
    request = RepairRequest(
        request_id='repair-imports',
        mode='repair',
        previous_generation_request_id='generate-imports',
        change_request={
            'title': 'Полнотекстовый поиск с результатами',
            'description': 'Новый метод должен возвращать SearchResult.',
            'constraints': [
                'Для контекстного фрагмента использовать build_context_fragment.',
                'Для позиций совпадений использовать find_match_positions.',
            ],
            'notes': [],
        },
        error_context={
            'verification_summary': {
                'failed_blocks': [
                    {
                        'name': 'patch_static_semantics',
                        'issues': [
                            {
                                'code': 'unknown_runtime_name',
                                'message': 'uses `SearchResult` but it is not imported',
                                'unknown_names': ['SearchResult', 'build_context_fragment', 'find_match_positions'],
                            }
                        ],
                    }
                ]
            }
        },
        previous_artifact={
            'operation': 'insert_after_symbol',
            'target_file': 'note/note_storage.py',
            'target_qualname': 'note.note_storage.NoteStorage',
            'insert_after': 'note.note_storage.NoteStorage',
            'code': 'def search_results_by_content(self, query):\n    return [SearchResult(note=None, preview="", match_positions=[])]',
        },
        project_context={
            'target_symbol': {
                'qualname': 'note.note_storage.NoteStorage',
                'name': 'NoteStorage',
                'kind': 'class',
                'source': 'class NoteStorage:\n    pass\n',
            },
            'required_contracts': [
                {'qualname': 'note.note_search.build_context_fragment', 'name': 'build_context_fragment'},
                {'qualname': 'note.note_search.find_match_positions', 'name': 'find_match_positions'},
            ],
            'model_surfaces': [
                {'name': 'SearchResult', 'qualname': 'note.note_search.SearchResult'},
            ],
            'contract_context': {'related_symbols': []},
            'module_outline': [],
        },
        target={'file_path': 'note/note_storage.py', 'qualname': 'note.note_storage.NoteStorage'},
    )

    prompt = build_repair_user_prompt(template, request, runtime_config=config)

    assert 'Required repair import_changes' in prompt
    assert '"module": "note.note_search"' in prompt
    assert '"SearchResult"' in prompt
    assert '"build_context_fragment"' in prompt
    assert '"find_match_positions"' in prompt
    assert 'обязательно включи перечисленные элементы в поле import_changes' in prompt


def test_test_prompts_include_target_derived_strategy_for_self_helpers() -> None:
    config = load_config('config.yaml')
    request = _request()
    request.target.update({
        'qualname': 'support_app.storage.NoteStorage',
        'file_path': 'support_app/storage.py',
        'operation': 'insert_after_symbol',
        'insert_scope': 'class_body',
        'expected_new_symbol_kind': 'method',
        'parent_qualname': 'support_app.storage.NoteStorage',
    })
    artifact = {
        'operation': 'insert_after_symbol',
        'insert_scope': 'class_body',
        'expected_new_symbol_kind': 'method',
        'parent_qualname': 'support_app.storage.NoteStorage',
        'code': (
            'def search_results(self, query):\n'
            '    notes = self.search_by_content(query)\n'
            '    return [build_preview(note.content, query) for note in notes]\n'
        ),
    }
    planner_template = Path('prompts/test_planner_user_template.txt').read_text(encoding='utf-8')
    generator_template = Path('prompts/test_generator_user_template.txt').read_text(encoding='utf-8')

    planner_prompt, _ = build_test_planner_user_prompt(
        planner_template,
        request,
        runtime_config=config,
        generated_code_artifact=artifact,
        available_user_chars=20000,
    )
    generator_prompt, _ = build_test_generator_user_prompt(
        generator_template,
        request,
        generated_test_file='tests/test_generated.py',
        example_test_source='',
        runtime_config=config,
        available_user_chars=20000,
        generated_code_artifact=artifact,
        test_plan={'target_symbol': 'support_app.storage.NoteStorage.search_results'},
    )

    for prompt in (planner_prompt, generator_prompt):
        assert 'Target-derived test data strategy' in prompt
        assert 'search_by_content' in prompt
        assert 'не создавай скрытые атрибуты состояния' in prompt
        assert 'patch должен менять binding в модуле target-кода' in prompt


def test_test_prompts_include_parent_constructor_path_guidance() -> None:
    config = load_config('config.yaml')
    request = _request()
    request.target.update({
        'qualname': 'support_app.storage.NoteStorage',
        'file_path': 'support_app/storage.py',
        'operation': 'insert_after_symbol',
        'insert_scope': 'class_body',
        'expected_new_symbol_kind': 'method',
        'parent_qualname': 'support_app.storage.NoteStorage',
    })
    request.project_context['full_file_source'] = (
        'from pathlib import Path\n\n'
        'class NoteStorage:\n'
        '    def __init__(self, base_dir: Path) -> None:\n'
        '        self.base_dir = base_dir\n'
        '    def search_by_content(self, query: str):\n'
        '        return []\n'
    )
    artifact = {
        'operation': 'insert_after_symbol',
        'insert_scope': 'class_body',
        'expected_new_symbol_kind': 'method',
        'parent_qualname': 'support_app.storage.NoteStorage',
        'code': (
            'def search_results(self, query):\n'
            '    notes = self.search_by_content(query)\n'
            '    return notes\n'
        ),
    }
    planner_template = Path('prompts/test_planner_user_template.txt').read_text(encoding='utf-8')
    generator_template = Path('prompts/test_generator_user_template.txt').read_text(encoding='utf-8')

    planner_prompt, _ = build_test_planner_user_prompt(
        planner_template,
        request,
        runtime_config=config,
        generated_code_artifact=artifact,
        available_user_chars=25000,
    )
    generator_prompt, _ = build_test_generator_user_prompt(
        generator_template,
        request,
        generated_test_file='tests/test_generated.py',
        example_test_source='',
        runtime_config=config,
        available_user_chars=25000,
        generated_code_artifact=artifact,
        test_plan={'target_symbol': 'support_app.storage.NoteStorage.search_results'},
    )

    for prompt in (planner_prompt, generator_prompt):
        assert 'Visible parent constructor contract for tests' in prompt
        assert 'NoteStorage(base_dir: Path)' in prompt
        assert 'Path/PurePath' in prompt
        assert 'а не строку' in prompt
        assert 'target_obj = NoteStorage(base_dir=tmp_path)' in prompt
        assert 'tmp_path` как параметр pytest-тестовой функции' in prompt


def test_test_generator_keeps_constructor_guidance_when_full_file_is_trimmed() -> None:
    config = load_config('config.yaml')
    request = _request()
    request.target.update({
        'qualname': 'support_app.storage.NoteStorage',
        'file_path': 'support_app/storage.py',
        'operation': 'insert_after_symbol',
        'insert_scope': 'class_body',
        'expected_new_symbol_kind': 'method',
        'parent_qualname': 'support_app.storage.NoteStorage',
    })
    long_header = '"""' + ('large module header\n' * 1200) + '"""\n'
    request.project_context['full_file_source'] = (
        long_header
        + 'from pathlib import Path\n\n'
        + 'class NoteStorage:\n'
        + '    def __init__(self, base_dir: Path) -> None:\n'
        + '        self.base_dir = base_dir\n'
    )
    artifact = {
        'operation': 'insert_after_symbol',
        'insert_scope': 'class_body',
        'expected_new_symbol_kind': 'method',
        'parent_qualname': 'support_app.storage.NoteStorage',
        'code': 'def search_results(self, query):\n    return []\n',
    }
    generator_template = Path('prompts/test_generator_user_template.txt').read_text(encoding='utf-8')

    prompt, _ = build_test_generator_user_prompt(
        generator_template,
        request,
        generated_test_file='tests/test_generated.py',
        example_test_source='',
        runtime_config=config,
        available_user_chars=12000,
        generated_code_artifact=artifact,
        test_plan={'target_symbol': 'support_app.storage.NoteStorage.search_results'},
    )

    assert 'Visible parent constructor contract for tests' in prompt
    assert 'NoteStorage(base_dir: Path)' in prompt
    assert 'target_obj = NoteStorage(base_dir=tmp_path)' in prompt


def test_replace_symbol_prompts_disallow_nested_helpers_and_stale_docstring_requirements() -> None:
    coder_template = Path('prompts/coder_user_template.txt').read_text(encoding='utf-8')
    repair_template = Path('prompts/repair_user_template.txt').read_text(encoding='utf-8')
    planner_template = Path('prompts/planner_user_template.txt').read_text(encoding='utf-8')
    repair_planner_template = Path('prompts/repair_planner_user_template.txt').read_text(encoding='utf-8')

    assert 'Не объявляй внутри него вложенные def/class/helper-symbols' in coder_template
    assert 'Вспомогательную логику реализуй прямо в теле target symbol' in coder_template
    assert 'старый docstring' in coder_template
    assert 'исходный запрос пользователя как источник истины' in coder_template

    assert 'nested symbols' in repair_template
    assert 'Нельзя просто переименовать вложенный helper' in repair_template
    assert 'полностью убери вложенное объявление' in repair_template
    assert 'не меняй requested insert_scope' in repair_template

    assert 'Не добавляй в explicit_requirements требования из старого docstring' in planner_template
    assert 'запрос пользователя имеет приоритет' in planner_template

    assert 'nested symbols' in repair_planner_template
    assert 'Не планируй переименование helper-функции' in repair_planner_template


def test_code_and_repair_parsers_normalize_insert_scope_aliases() -> None:
    from codegenerator.generation.coder import parse_code_response
    from codegenerator.generation.repair import parse_repair_response

    code_payload = (
        '{'
        '"target_file":"note/note_storage.py",'
        '"operation":"replace_symbol",'
        '"insert_scope":"class",'
        '"code":"def generate_filename(self, note):\\n    return \\\"x.note\\\""'
        '}'
    )
    repair_payload = (
        '{'
        '"target_file":"note/note_storage.py",'
        '"operation":"replace_symbol",'
        '"insert_scope":"module",'
        '"code":"def helper():\\n    return None"'
        '}'
    )

    assert parse_code_response(code_payload)['insert_scope'] == 'class_body'
    assert parse_repair_response(repair_payload)['insert_scope'] == 'module_body'


def test_prompts_render_explicit_request_output_obligations_without_example_specific_logic() -> None:
    from codegenerator.config import load_config
    from codegenerator.models.requests import GenerationRequest, RepairRequest
    from codegenerator.prompts.prompt_builder import (
        build_coder_user_prompt,
        build_repair_user_prompt,
        build_test_generator_user_prompt,
        build_test_planner_user_prompt,
    )

    config = load_config('config.yaml')
    change_request = {
        'title': 'Генерация безопасного имени файла заметки',
        'description': (
            'Реализовать генерацию имени файла заметки на основе темы и даты создания. '
            'Имя должно быть безопасным для файловой системы, содержать дату/время '
            'и заканчиваться расширением .note.'
        ),
        'constraints': [],
        'notes': [],
    }
    project_context = {
        'module_outline': [],
        'full_file_source': 'from pathlib import Path\nfrom note.note_model import Note\n',
        'target_symbol': {
            'qualname': 'note.note_storage.NoteStorage.generate_filename',
            'name': 'generate_filename',
            'kind': 'method',
            'source': (
                'def generate_filename(self, note: Note) -> str:\n'
                '    """Returns filename without extension."""\n'
                '    raise NotImplementedError\n'
            ),
        },
        'contract_context': {'related_symbols': []},
        'model_surfaces': [
            {
                'name': 'Note',
                'qualname': 'note.note_model.Note',
                'constructor_fields': ['subject', 'content', 'created_at'],
            }
        ],
    }
    generation_request = GenerationRequest(
        request_id='literal-obligations',
        mode='generate',
        change_request=change_request,
        target={
            'qualname': 'note.note_storage.NoteStorage.generate_filename',
            'file_path': 'note/note_storage.py',
            'operation': 'replace_symbol',
            'insert_scope': 'class_body',
            'expected_new_symbol_kind': 'method',
            'parent_qualname': 'note.note_storage.NoteStorage',
        },
        project_context=project_context,
        options={},
    )

    coder_prompt, _ = build_coder_user_prompt(
        Path('prompts/coder_user_template.txt').read_text(encoding='utf-8'),
        generation_request,
        planner_result={'explicit_requirements': ['Вернуть имя без расширения']},
        runtime_config=config,
        available_user_chars=20000,
    )
    planner_prompt, _ = build_test_planner_user_prompt(
        Path('prompts/test_planner_user_template.txt').read_text(encoding='utf-8'),
        generation_request,
        runtime_config=config,
        generated_code_artifact={
            'code': 'def generate_filename(self, note):\n    return "Meeting_20240315143022"\n'
        },
        available_user_chars=20000,
    )
    generator_prompt, _ = build_test_generator_user_prompt(
        Path('prompts/test_generator_user_template.txt').read_text(encoding='utf-8'),
        generation_request,
        generated_test_file='tests/test_generated.py',
        example_test_source='',
        runtime_config=config,
        available_user_chars=20000,
        generated_code_artifact={
            'code': 'def generate_filename(self, note):\n    return "Meeting_20240315143022"\n'
        },
        test_plan={'target_symbol': 'note.note_storage.NoteStorage.generate_filename'},
    )
    repair_request = RepairRequest(
        request_id='literal-obligations-repair',
        mode='repair',
        previous_generation_request_id='literal-obligations',
        change_request=change_request,
        error_context={'verification_summary': {'failed_blocks': []}},
        previous_artifact={
            'operation': 'replace_symbol',
            'target_file': 'note/note_storage.py',
            'target_qualname': 'note.note_storage.NoteStorage.generate_filename',
            'insert_after': 'note.note_storage.NoteStorage.generate_filename',
            'code': 'def generate_filename(self, note):\n    return "Meeting_20240315143022"\n',
        },
        project_context=project_context,
        target={'file_path': 'note/note_storage.py', 'qualname': 'note.note_storage.NoteStorage.generate_filename'},
    )
    repair_prompt = build_repair_user_prompt(
        Path('prompts/repair_user_template.txt').read_text(encoding='utf-8'),
        repair_request,
        runtime_config=config,
    )

    for prompt in (coder_prompt, planner_prompt, generator_prompt, repair_prompt):
        assert 'Явные требования запроса к результату и литералам' in prompt
        assert 'заканчиваться расширением .note' in prompt
        assert '- .note' in prompt
        assert 'стар' in prompt


def test_request_literal_extractor_is_general_and_includes_function_names_without_hardcoded_extensions() -> None:
    from codegenerator.prompts.prompt_builder import _render_request_output_obligations

    block = _render_request_output_obligations(
        {
            'title': 'Добавить вывод результата',
            'description': 'Метод render_summary должен возвращать строку в формате REPORT_YYYYMMDD.json.',
            'constraints': ['Не менять render_summary.'],
        }
    )

    assert 'Явные требования запроса к результату и литералам' in block
    assert 'REPORT_YYYYMMDD.json' in block
    assert 'render_summary' in block


def test_code_parser_normalizes_decorated_class_body_method_indent_and_kind() -> None:
    from codegenerator.generation.coder import parse_code_response

    payload = (
        '{'
        '"target_file":"note/note_search.py",'
        '"operation":"insert_after_symbol",'
        '"insert_scope":"class_body",'
        '"expected_new_symbol_kind":"property",'
        '"code":"@property\\n    def note_id(self) -> str | None:\\n        return getattr(self.note, \\\"id\\\", None)"'
        '}'
    )

    parsed = parse_code_response(payload)

    assert parsed['expected_new_symbol_kind'] == 'method'
    assert parsed['code'].startswith('@property\ndef note_id')
    assert '\n    return getattr' in parsed['code']


def test_repair_parser_normalizes_outer_indented_decorated_class_body_method() -> None:
    from codegenerator.generation.repair import parse_repair_response

    payload = (
        '{'
        '"target_file":"note/note_search.py",'
        '"operation":"insert_after_symbol",'
        '"insert_scope":"class_body",'
        '"expected_new_symbol_kind":"property",'
        '"code":"    @property\\n    def note_id(self) -> str | None:\\n        return getattr(self.note, \\\"id\\\", None)"'
        '}'
    )

    parsed = parse_repair_response(payload)

    assert parsed['expected_new_symbol_kind'] == 'method'
    assert parsed['code'].startswith('@property\ndef note_id')
    assert '\n    return getattr' in parsed['code']


def test_generation_prompts_allow_decorated_class_body_methods_safely() -> None:
    coder_template = Path('prompts/coder_user_template.txt').read_text(encoding='utf-8')
    repair_template = Path('prompts/repair_user_template.txt').read_text(encoding='utf-8')

    assert 'decorator-строк' in coder_template
    assert '@property' in coder_template
    assert 'одном базовом уровне отступа' in coder_template
    assert 'expected_new_symbol_kind оставляй "method"' in coder_template

    assert 'decorator-строк' in repair_template
    assert 'unexpected indent в decorated method' in repair_template
    assert 'expected_new_symbol_kind из параметров задачи' in repair_template



def test_replace_symbol_preservation_guidance_is_generic_and_source_derived() -> None:
    from codegenerator.prompts.prompt_builder import _render_replace_symbol_preservation_guidance

    source = '''
def update_item(self, item):
    if not isinstance(item, Item):
        raise TypeError("bad item")
    path = self.path_for(item)
    if item.identifier is None:
        item.identifier = path.stem
    data = {"name": item.name, "identifier": item.identifier}
    self.writer.write(path, data)
    return str(path)
'''
    block = _render_replace_symbol_preservation_guidance(
        operation='replace_symbol',
        change_request={
            'title': 'Обновить значение при сохранении',
            'description': 'При сохранении нужно обновить служебное значение.',
            'constraints': ['Сохранить текущую структуру сохранения и формат данных.'],
        },
        target_source=source,
    )

    assert 'Сохраняемые элементы' not in block
    assert 'Порядок сохраняемых действий' in block
    assert 'if item.identifier is None' in block
    assert 'item.identifier = path.stem' in block
    assert 'path_for(item)' in block
    assert 'item.identifier' in block
    assert 'name' in block
    assert 'return' not in block.lower() or 'str(path)' in block
    assert 'NoteStorage' not in block
    assert 'updated_at' not in block


def test_replace_symbol_preservation_guidance_is_not_rendered_without_preserve_request() -> None:
    from codegenerator.prompts.prompt_builder import _render_replace_symbol_preservation_guidance

    block = _render_replace_symbol_preservation_guidance(
        operation='replace_symbol',
        change_request={
            'title': 'Добавить проверку',
            'description': 'Метод должен вернуть True для валидного значения.',
            'constraints': [],
        },
        target_source='def check(self, value):\n    return bool(value)\n',
    )

    assert block == ''


def test_context_budget_preserves_longer_target_for_replace_symbol_preserve_requests() -> None:
    class Config:
        class Budget:
            generate_module_outline_keep = 4
            generate_related_tests_keep = 0
            generate_related_test_source_limit = 0
            generate_target_source_limit = 100
            generate_test_drop_reference = True
            generate_test_module_outline_keep = 2
            generate_test_related_tests_keep = 0
            generate_test_related_test_source_limit = 0
            generate_test_target_source_limit = 100
            repair_drop_reference = True
            repair_module_outline_keep = 2
            repair_verification_message_limit = 100
            repair_previous_artifact_code_limit = 100
            repair_related_tests_keep = 0
            repair_related_test_source_limit = 0
            repair_target_source_limit = 100

        budget_strategy = Budget()
        coder_max_contract_symbols = 0
        coder_max_contract_symbol_chars = 0
        test_prompt_contract_symbols = 0
        test_prompt_contract_symbol_chars = 0
        repair_max_contract_symbols = 0
        repair_max_contract_symbol_chars = 0

    long_source = 'def save(self, value):\n' + '\n'.join(f'    step_{i} = value' for i in range(80)) + '\n    return value\n'
    request = {
        'change_request': {
            'title': 'Обновить сохранение',
            'description': 'Нужно изменить одно значение.',
            'constraints': ['Сохранить текущую структуру и формат результата.'],
        },
        'target': {'operation': 'replace_symbol'},
        'project_context': {
            'target_symbol': {'source': long_source},
            'related_tests': [],
            'contract_context': {'related_symbols': []},
            'module_outline': [],
        },
        'reference_context': {'reference_artifacts': []},
        'options': {},
    }

    
    class Logger:
        def info(self, *args, **kwargs):
            pass

    trimmed, trim_log = apply_budget_strategy(request, 'generate', 1000, logger=Logger(), config=Config())

    kept_source = trimmed['project_context']['target_symbol']['source']
    assert len(kept_source) > 100
    assert 'step_79 = value' in kept_source


def test_replace_symbol_preservation_block_is_rendered_in_coder_prompt() -> None:
    from codegenerator.config import load_config
    from codegenerator.models.requests import GenerationRequest
    from codegenerator.prompts.prompt_builder import build_coder_user_prompt

    template = Path('prompts/coder_user_template.txt').read_text(encoding='utf-8')
    config = load_config('config.yaml')
    source = '''def update_item(self, item):
    if item.identifier is None:
        item.identifier = self.identifier_for(item)
    data = {"name": item.name, "identifier": item.identifier}
    self.writer.write(item, data)
    return str(item.identifier)
'''
    request = GenerationRequest(
        request_id='preserve-coder',
        mode='generate',
        change_request={
            'title': 'Обновить значение при сохранении',
            'description': 'При сохранении нужно обновить одно служебное значение.',
            'constraints': ['Сохранить текущую структуру и формат данных.'],
        },
        target={
            'qualname': 'app.storage.Storage.update_item',
            'file_path': 'app/storage.py',
            'operation': 'replace_symbol',
            'insert_scope': 'class_body',
        },
        project_context={
            'module_outline': [],
            'full_file_source': '',
            'target_symbol': {
                'qualname': 'app.storage.Storage.update_item',
                'name': 'update_item',
                'kind': 'method',
                'source': source,
            },
            'related_tests': [],
            'contract_context': {'related_symbols': []},
        },
    )

    prompt, _metrics = build_coder_user_prompt(template, request, {}, config)

    assert 'Сохраняемые элементы текущей реализации' in prompt
    assert 'Порядок сохраняемых действий' in prompt
    assert 'item.identifier = self.identifier_for(item)' in prompt
    assert 'self.writer.write(item, data)' in prompt
    assert 'str(item.identifier)' in prompt
    assert 'NoteStorage' not in prompt


def test_repair_template_has_preservation_block_placeholder() -> None:
    template = Path('prompts/repair_user_template.txt').read_text(encoding='utf-8')

    assert '{preservation_guidance_block}' in template
    assert 'Сохраняемые элементы текущей реализации' in template


def test_coder_prompt_renders_available_imports_block() -> None:
    from codegenerator.config import load_config
    from codegenerator.models.requests import GenerationRequest
    from codegenerator.prompts.prompt_builder import build_coder_user_prompt

    template = Path('prompts/coder_user_template.txt').read_text(encoding='utf-8')
    config = load_config('config.yaml')
    request = GenerationRequest(
        request_id='available-imports-coder',
        mode='generate',
        change_request={
            'title': 'Обновить метод',
            'description': 'Использовать текущее время.',
            'constraints': ['Сохранить текущую структуру.'],
        },
        target={
            'qualname': 'app.storage.Storage.save',
            'file_path': 'app/storage.py',
            'operation': 'replace_symbol',
            'insert_scope': 'class_body',
        },
        project_context={
            'available_imports': [
                {
                    'name': 'datetime',
                    'kind': 'from_import',
                    'module': 'datetime',
                    'imported': 'datetime',
                    'source': 'from datetime import datetime',
                },
                {
                    'name': 'json',
                    'kind': 'import',
                    'module': 'json',
                    'source': 'import json',
                },
            ],
            'module_outline': [],
            'target_symbol': {
                'qualname': 'app.storage.Storage.save',
                'name': 'save',
                'kind': 'method',
                'source': 'def save(self, item):\n    return item\n',
            },
            'related_tests': [],
            'contract_context': {'related_symbols': []},
        },
    )

    prompt, metrics = build_coder_user_prompt(template, request, {}, config)

    assert 'Доступные imports и имена целевого файла' in prompt
    assert 'datetime: from datetime import datetime' in prompt
    assert 'json: import json' in prompt
    assert metrics['coder_available_imports_chars'] > 0


def test_repair_prompt_marks_import_only_scope() -> None:
    from codegenerator.config import load_config
    from codegenerator.models.requests import RepairRequest
    from codegenerator.prompts.prompt_builder import build_repair_user_prompt

    template = Path('prompts/repair_user_template.txt').read_text(encoding='utf-8')
    config = load_config('config.yaml')
    request = RepairRequest(
        request_id='repair-import-only',
        mode='repair',
        previous_generation_request_id='generate-save',
        change_request={
            'title': 'Исправить импорт',
            'description': 'Использовать доступный импорт.',
            'constraints': [],
        },
        error_context={
            'verification_summary': {
                'failed_blocks': [
                    {
                        'name': 'patch_static_semantics',
                        'issues': [
                            {
                                'code': 'unresolved_import_change_module',
                                'message': 'bad import',
                            }
                        ],
                    }
                ]
            }
        },
        previous_artifact={
            'target_file': 'app/storage.py',
            'target_symbol': 'app.storage.Storage.save',
            'operation': 'replace_symbol',
            'code': 'def save(self, item):\n    return item\n',
            'import_changes': [{'action': 'add_import', 'module': 'datetime'}],
        },
        project_context={
            'available_imports': [
                {
                    'name': 'datetime',
                    'kind': 'from_import',
                    'module': 'datetime',
                    'imported': 'datetime',
                    'source': 'from datetime import datetime',
                }
            ],
            'target_symbol': {
                'qualname': 'app.storage.Storage.save',
                'name': 'save',
                'kind': 'method',
                'source': 'def save(self, item):\n    return item\n',
            },
            'module_outline': [],
            'contract_context': {'related_symbols': []},
        },
    )

    prompt = build_repair_user_prompt(template, request, config)

    assert 'Область repair' in prompt
    assert 'только imports' in prompt
    assert 'Доступные imports и имена целевого файла' in prompt
    assert 'datetime: from datetime import datetime' in prompt


def test_test_prompts_prefer_constructor_fields_over_post_init_assignment() -> None:
    planner_template = Path('prompts/test_planner_user_template.txt').read_text(encoding='utf-8')
    generator_template = Path('prompts/test_generator_user_template.txt').read_text(encoding='utf-8')

    expected = 'передавай его через keyword-аргумент конструктора'
    assert expected in planner_template
    assert expected in generator_template
    assert 'не ожидай фиксированную заранее придуманную дату' in planner_template
    assert 'не ожидай фиксированную заранее придуманную дату' in generator_template


def test_generated_test_review_template_flags_removed_dict_keys() -> None:
    template = Path('prompts/generated_test_review_user_template.txt').read_text(encoding='utf-8')

    assert 'удаление ключа из явно создаваемого словаря' in template
    assert 'считай это production_risk' in template
    assert 'передать значение через конструктор' in template

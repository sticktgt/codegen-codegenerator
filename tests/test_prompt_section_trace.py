from __future__ import annotations

from codegenerator.orchestration.generation_service import _add_prompt_section_trace
from codegenerator.models.requests import GenerationRequest


def _request() -> GenerationRequest:
    return GenerationRequest(
        request_id='req-1',
        mode='generate',
        change_request={'title': 'T', 'description': 'D'},
        target={'qualname': 'app.service.Service.run', 'operation': 'replace_symbol'},
        project_context={'target_symbol': {'qualname': 'app.service.Service.run'}},
    )


def test_prompt_section_trace_records_final_coder_sections() -> None:
    trace = {'request_id': 'req-1', 'mode': 'generate', 'steps': []}
    metrics = {
        'coder_prompt_section_sizes_final': {
            'stage': 'final',
            'request': 120,
            'target': 240,
            'full_file': 0,
        },
        'coder_trim_steps': ['skipped full_file due to soft size target'],
    }

    _add_prompt_section_trace(
        trace,
        stage='coder',
        request=_request(),
        user_prompt='user prompt',
        system_prompt='system',
        metrics=metrics,
    )

    payload = trace['steps'][0]['payload']
    assert trace['steps'][0]['step'] == 'coder_prompt_section_trace'
    assert payload['total_prompt_chars'] == len('user prompt') + len('system')
    assert payload['key_symbols'] == ['app.service.Service.run']
    sections = {item['name']: item for item in payload['sections']}
    assert sections['request']['status'] == 'included'
    assert sections['target']['actual_chars'] == 240
    assert sections['full_file']['status'] == 'skipped'


def test_prompt_section_trace_summarizes_generic_metrics() -> None:
    trace = {'request_id': 'req-1', 'mode': 'generate', 'steps': []}

    _add_prompt_section_trace(
        trace,
        stage='test_generator',
        request=_request(),
        user_prompt='abc',
        system_prompt='z',
        metrics={
            'test_related_tests_count': 2,
            'test_related_test_chars': 300,
            'test_reference_chars': 0,
        },
    )

    sections = {item['name']: item for item in trace['steps'][0]['payload']['sections']}
    assert sections['related_tests']['count'] == 2
    assert sections['related_test']['actual_chars'] == 300
    assert sections['reference']['status'] == 'skipped'

from codegenerator.orchestration.generation_service import (
    OperationMismatchError,
    _canonicalize_code_result_for_request,
)


def test_canonicalize_code_result_reports_operation_mismatch_structurally() -> None:
    try:
        _canonicalize_code_result_for_request(
            {'operation': 'replace_symbol', 'code': 'def x():\n    pass'},
            expected_operation='insert_after_symbol',
            target_qualname='app.Service.anchor',
            request_target={},
        )
    except OperationMismatchError as exc:
        assert exc.actual_operation == 'replace_symbol'
        assert exc.expected_operation == 'insert_after_symbol'
        assert 'replace_symbol' in str(exc)
        assert 'insert_after_symbol' in str(exc)
    else:
        raise AssertionError('OperationMismatchError was not raised')

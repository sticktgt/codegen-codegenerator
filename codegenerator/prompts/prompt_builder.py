from __future__ import annotations

import json
from typing import Any

from codegenerator.models.requests import GenerationRequest, RepairRequest


def _pretty(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def merged_constraints(req_constraints: list[str], default_constraints: list[str]) -> list[str]:
    out: list[str] = []
    for item in [*default_constraints, *req_constraints]:
        if item and item not in out:
            out.append(item)
    return out


def build_planner_user_prompt(template_text: str, request: GenerationRequest, default_constraints: list[str]) -> str:
    cr = request.change_request
    target = request.target
    constraints = merged_constraints(cr.get('constraints', []), default_constraints)
    return template_text.format(
        experiment_name=request.request_id,
        operation=target.get('operation', 'replace_symbol'),
        target_file=target.get('file_path', ''),
        target_symbol=target.get('qualname', ''),
        insert_after=target.get('insert_after') or 'null',
        reference_symbol='null',
        request=((cr.get('title', '') + "\n" + cr.get('description', '')).strip()),
    ) + "\n\nОграничения:\n" + _pretty(constraints)


def build_coder_user_prompt(template_text: str, request: GenerationRequest, planner_result: dict[str, Any]) -> str:
    pc = request.project_context or {}
    return template_text.format(
        operation=request.target.get('operation', 'replace_symbol'),
        target_file=request.target.get('file_path', ''),
        target_symbol=request.target.get('qualname', ''),
        insert_after=request.target.get('insert_after') or 'null',
        reference_symbol='null',
        planner_json=_pretty(planner_result),
        request=((request.change_request.get('title', '') + "\n" + request.change_request.get('description', '')).strip()),
        module_outline=_pretty(pc.get('module_outline', [])),
        target_function=_pretty(pc.get('target_symbol') or pc.get('target_function') or {}),
        reference_function='null',
        full_file_source=pc.get('full_file_source', ''),
    ) + "\n\nReference context:\n" + _pretty(request.reference_context)


def build_repair_user_prompt(template_text: str, request: RepairRequest) -> str:
    project_context = request.project_context or {}
    target_symbol = project_context.get('target_symbol') or {}
    module_outline = project_context.get('module_outline', [])
    full_file_source = project_context.get('full_file_source', '')

    values = {
        'operation': request.previous_artifact.get('operation', 'replace_symbol'),
        'target_file': request.previous_artifact.get('target_file', ''),
        'target_symbol': request.previous_artifact.get('target_qualname', request.previous_artifact.get('target_symbol', '')),
        'insert_after': request.previous_artifact.get('insert_after') or 'null',
        'request': request.error_context.get('summary', 'repair request'),
        'planner_json': _pretty({'repair_for': request.previous_generation_request_id}),
        'verification_summary': _pretty(request.error_context),
        'verification_summary_json': _pretty(request.error_context),
        'module_outline': _pretty(module_outline),
        'target_function': _pretty(target_symbol),
        'full_file_source': full_file_source,
        'current_generated_code': request.previous_artifact.get('code', ''),
        'module_outline_block': '\n\nModule outline:\n' + _pretty(module_outline) if module_outline else '',
        'target_function_block': '\n\nTarget function:\n' + _pretty(target_symbol) if target_symbol else '',
        'reference_function_block': '',
        'full_file_source_block': '\n\nFull file source:\n' + full_file_source if full_file_source else '',
    }
    return template_text.format(**values) + "\n\nReference context:\n" + _pretty(request.reference_context)


def build_test_generator_user_prompt(template_text: str, request: GenerationRequest, planner_result: dict[str, Any], generated_test_file: str, example_test_source: str) -> str:
    pc = request.project_context or {}
    return template_text.format(
        operation=request.target.get('operation', 'replace_symbol'),
        target_file=request.target.get('file_path', ''),
        target_symbol=request.target.get('qualname', ''),
        planner_json=_pretty(planner_result),
        request=((request.change_request.get('title', '') + "\n" + request.change_request.get('description', '')).strip()),
        module_outline=_pretty(pc.get('module_outline', [])),
        full_file_source=pc.get('full_file_source', ''),
        generated_test_file=generated_test_file,
        example_test_source=example_test_source,
    )

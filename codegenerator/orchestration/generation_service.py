from __future__ import annotations
from pathlib import Path
from typing import Any
from dataclasses import asdict, is_dataclass
from codegenerator.config import load_config
from codegenerator.logger import get_logger
from codegenerator.llm.gateway import create_client, call_model
from codegenerator.prompts.prompt_loader import load_prompts
from codegenerator.prompts.prompt_builder import build_planner_user_prompt, build_coder_user_prompt, build_repair_user_prompt, build_test_generator_user_prompt
from codegenerator.models.requests import GenerationRequest, RepairRequest
from codegenerator.models.results import GenerationResult
from codegenerator.models.artifacts import CodeArtifact, TestArtifact
from codegenerator.generation.planner import parse_planner_response
from codegenerator.generation.coder import parse_code_response
from codegenerator.generation.repair import parse_repair_response
from codegenerator.generation.test_generator import build_generated_test_filename, parse_test_response
from codegenerator.trace.trace_store import build_trace_path, save_trace
from codegenerator.validation.local_checks import validate_russian_error_messages
logger = get_logger('codegenerator.service')

def _base_trace(req_id: str, mode: str) -> dict[str, Any]:
    return {'request_id': req_id, 'mode': mode, 'steps': []}

def _serialize_meta(meta: Any) -> dict[str, Any]:
    if is_dataclass(meta):
        return asdict(meta)
    if hasattr(meta, 'to_dict'):
        return meta.to_dict()
    if hasattr(meta, '__dict__'):
        return dict(meta.__dict__)
    return {'repr': repr(meta)}

def _add_step(trace: dict[str, Any], step: str, payload: dict[str, Any]) -> None:
    trace['steps'].append({'step': step, 'payload': payload})

def generate(request: GenerationRequest, config_path: str) -> GenerationResult:
    config = load_config(config_path)
    prompts = load_prompts(config)
    client = create_client(config)
    trace = _base_trace(request.request_id, 'generate')
    trace_path = build_trace_path(config.trace.output_dir, request.request_id)
    try:
        planner_prompt = build_planner_user_prompt(prompts['planner_user_template'], request, config.defaults_constraints)
        requested_test_mode = str(request.options.get('generate_test_mode', config.test_generation_mode))
        logger.info('generate request_id=%s models planner=%s coder=%s test=%s repair=%s test_mode=%s', request.request_id, config.models.planner_model, config.models.coder_model, config.models.test_generator_model, config.models.repair_model, requested_test_mode)
        try:
            planner_raw, planner_meta = call_model(client=client, model=config.models.planner_model, system_prompt=prompts['system_rules'], user_prompt=planner_prompt, think=config.ollama.think, config=config, step='planner')
            planner_result = parse_planner_response(planner_raw.content)
            _add_step(trace, 'planner', {'meta': _serialize_meta(planner_meta), 'prompt': planner_prompt, 'raw': planner_raw.raw, 'content': planner_raw.content, 'parsed': planner_result})
        except Exception as e:
            _add_step(trace, 'planner_error', {'prompt': planner_prompt, 'error': str(e)})
            raise

        coder_prompt, coder_context_metrics = build_coder_user_prompt(prompts['coder_user_template'], request, planner_result, config)
        logger.info('coder context request_id=%s before=%s after=%s target_chars=%s full_file_chars=%s reference_chars=%s references=%s', request.request_id, coder_context_metrics.get('coder_prompt_chars_before_trim'), coder_context_metrics.get('coder_prompt_chars_after_trim'), coder_context_metrics.get('coder_target_chars'), coder_context_metrics.get('coder_full_file_chars'), coder_context_metrics.get('coder_reference_chars'), coder_context_metrics.get('reference_count'))
        try:
            coder_raw, coder_meta = call_model(client=client, model=config.models.coder_model, system_prompt=prompts['system_rules'], user_prompt=coder_prompt, think=config.ollama.think, config=config, step='coder')
            code_result = parse_code_response(coder_raw.content)
            _add_step(trace, 'coder', {'meta': _serialize_meta(coder_meta), 'prompt': coder_prompt, 'context_metrics': coder_context_metrics, 'raw': coder_raw.raw, 'content': coder_raw.content, 'parsed': code_result})
        except Exception as e:
            _add_step(trace, 'coder_error', {'prompt': coder_prompt, 'context_metrics': coder_context_metrics, 'error': str(e)})
            raise

        code_artifact = CodeArtifact(operation=code_result['operation'], target_qualname=request.target.get('qualname',''), target_file=code_result['target_file'], code=code_result['code'], insert_after=code_result.get('insert_after'))
        warnings=[]
        local_check = validate_russian_error_messages(code_artifact.code)
        if not local_check.get('ok', True):
            warnings.append('generated code contains non-russian ValueError messages')
        test_artifact = None
        mode = str(request.options.get('generate_test_mode', config.test_generation_mode))
        if mode == 'always' or (mode == 'if_missing' and not request.project_context.get('related_tests')):
            expected_test_file = build_generated_test_filename(request)
            logger.info('test generation request_id=%s mode=%s expected_test=%s', request.request_id, mode, expected_test_file)
            test_prompt = build_test_generator_user_prompt(prompts['test_generator_user_template'], request, planner_result, expected_test_file, prompts['test_generator_example_source'])
            test_raw, test_meta = call_model(client=client, model=config.models.test_generator_model, system_prompt=prompts['system_rules'], user_prompt=test_prompt, think=config.ollama.think, config=config, step='test_generator')
            test_result = parse_test_response(test_raw.content, expected_test_file)
            test_artifact = TestArtifact(file_path=test_result['test_file'], source_code=test_result['code'])
            _add_step(trace, 'test_generator', {'meta': _serialize_meta(test_meta), 'prompt': test_prompt, 'raw': test_raw.raw, 'content': test_raw.content, 'parsed': test_result})
        result = GenerationResult(request_id=request.request_id, status='ok', code_artifact=code_artifact, test_artifact=test_artifact, planner_result=planner_result, warnings=warnings, trace_path=str(trace_path))
        trace['result']=result.to_dict()
        save_trace(trace_path, trace)
        return result
    except Exception as e:
        logger.exception('generate failed')
        trace['error']={'type': type(e).__name__, 'message': str(e)}
        save_trace(trace_path, trace)
        return GenerationResult(request_id=request.request_id, status='error', trace_path=str(trace_path), error_type=type(e).__name__, message=str(e))



def generate_test(request: GenerationRequest, config_path: str) -> GenerationResult:
    config = load_config(config_path)
    prompts = load_prompts(config)
    client = create_client(config)
    trace = _base_trace(request.request_id, 'generate_test')
    trace_path = build_trace_path(config.trace.output_dir, request.request_id)
    try:
        planner_prompt = build_planner_user_prompt(prompts['planner_user_template'], request, config.defaults_constraints)
        logger.info('generate_test request_id=%s models planner=%s test=%s', request.request_id, config.models.planner_model, config.models.test_generator_model)
        planner_raw, planner_meta = call_model(client=client, model=config.models.planner_model, system_prompt=prompts['system_rules'], user_prompt=planner_prompt, think=config.ollama.think, config=config, step='planner')
        planner_result = parse_planner_response(planner_raw.content)
        _add_step(trace, 'planner', {'meta': _serialize_meta(planner_meta), 'prompt': planner_prompt, 'raw': planner_raw.raw, 'content': planner_raw.content, 'parsed': planner_result})

        expected_test_file = build_generated_test_filename(request)
        test_prompt = build_test_generator_user_prompt(prompts['test_generator_user_template'], request, planner_result, expected_test_file, prompts['test_generator_example_source'])
        test_raw, test_meta = call_model(client=client, model=config.models.test_generator_model, system_prompt=prompts['system_rules'], user_prompt=test_prompt, think=config.ollama.think, config=config, step='test_generator')
        test_result = parse_test_response(test_raw.content, expected_test_file)
        test_artifact = TestArtifact(file_path=test_result['test_file'], source_code=test_result['code'])
        _add_step(trace, 'test_generator', {'meta': _serialize_meta(test_meta), 'prompt': test_prompt, 'raw': test_raw.raw, 'content': test_raw.content, 'parsed': test_result})
        result = GenerationResult(request_id=request.request_id, status='ok', test_artifact=test_artifact, planner_result=planner_result, trace_path=str(trace_path))
        trace['result'] = result.to_dict()
        save_trace(trace_path, trace)
        return result
    except Exception as e:
        logger.exception('generate_test failed')
        trace['error']={'type': type(e).__name__, 'message': str(e)}
        save_trace(trace_path, trace)
        return GenerationResult(request_id=request.request_id, status='error', trace_path=str(trace_path), error_type=type(e).__name__, message=str(e))

def repair(request: RepairRequest, config_path: str) -> GenerationResult:
    config = load_config(config_path)
    prompts = load_prompts(config)
    client = create_client(config)
    trace = _base_trace(request.request_id, 'repair')
    trace_path = build_trace_path(config.trace.output_dir, request.request_id)
    try:
        repair_prompt = build_repair_user_prompt(prompts['repair_user_template'], request, config)
        logger.info('repair request_id=%s model=%s', request.request_id, config.models.repair_model)
        repair_raw, repair_meta = call_model(client=client, model=config.models.repair_model, system_prompt=prompts['system_rules'], user_prompt=repair_prompt, think=config.ollama.think, config=config, step='repair')
        try:
            repair_result = parse_repair_response(repair_raw.content)
        except Exception as e:
            _add_step(trace, 'repair_parse_error', {'meta': _serialize_meta(repair_meta), 'prompt': repair_prompt, 'raw': repair_raw.raw, 'content': repair_raw.content, 'error': str(e)})
            save_trace(trace_path, trace)
            return GenerationResult(request_id=request.request_id, status='error', trace_path=str(trace_path), error_type='invalid_repair_response', message=str(e))
        _add_step(trace, 'repair', {'meta': _serialize_meta(repair_meta), 'prompt': repair_prompt, 'raw': repair_raw.raw, 'content': repair_raw.content, 'parsed': repair_result})
        code_artifact = CodeArtifact(operation=repair_result['operation'], target_qualname=request.previous_artifact.get('target_qualname', request.previous_artifact.get('target_symbol','')), target_file=repair_result['target_file'], code=repair_result['code'], insert_after=repair_result.get('insert_after'))
        result = GenerationResult(request_id=request.request_id, status='ok', code_artifact=code_artifact, trace_path=str(trace_path))
        trace['result']=result.to_dict()
        save_trace(trace_path, trace)
        return result
    except Exception as e:
        logger.exception('repair failed')
        trace['error']={'type': type(e).__name__, 'message': str(e)}
        save_trace(trace_path, trace)
        return GenerationResult(request_id=request.request_id, status='error', trace_path=str(trace_path), error_type=type(e).__name__, message=str(e))

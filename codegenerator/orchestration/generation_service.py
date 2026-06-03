# codegenerator/orchestration/generation_service.py
from __future__ import annotations

import json

from dataclasses import asdict, is_dataclass
from typing import Any, Callable

from codegenerator.config import load_config
from codegenerator.context.budget import apply_budget_strategy
from codegenerator.generation.coder import parse_code_response
from codegenerator.generation.planner import (
    parse_planner_response,
    parse_test_planner_response,
)
from codegenerator.generation.repair import parse_repair_response, parse_repair_plan_response
from codegenerator.generation.test_generator import (
    build_generated_test_filename,
    parse_test_response,
)
from codegenerator.llm.gateway import call_model, create_client
from codegenerator.logger import get_logger
from codegenerator.models.artifacts import CodeArtifact, TestArtifact
from codegenerator.models.requests import GenerationRequest, RepairRequest
from codegenerator.models.results import GenerationResult
from codegenerator.parsing.json_utils import parse_json_object
from codegenerator.prompts.review_prompt_builder import GeneratedTestFailureReviewPromptBuilder
from codegenerator.prompts.prompt_builder import (
    build_coder_user_prompt,
    build_planner_user_prompt,
    build_repair_user_prompt,
    build_repair_planner_user_prompt,
    build_test_generator_user_prompt,
    build_test_planner_user_prompt,
)
from codegenerator.prompts.prompt_loader import load_prompts
from codegenerator.trace.trace_store import build_trace_path, save_trace
from codegenerator.validation.local_checks import validate_russian_error_messages

logger = get_logger("codegenerator.service")


def _base_trace(req_id: str, mode: str) -> dict[str, Any]:
    return {"request_id": req_id, "mode": mode, "steps": []}


def _serialize_meta(meta: Any) -> dict[str, Any]:
    if is_dataclass(meta):
        return asdict(meta)
    if hasattr(meta, "to_dict"):
        return meta.to_dict()
    if hasattr(meta, "__dict__"):
        return dict(meta.__dict__)
    return {"repr": repr(meta)}


def _add_step(trace: dict[str, Any], step: str, payload: dict[str, Any]) -> None:
    trace["steps"].append({"step": step, "payload": payload})




def _warning_messages_from_format_warnings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    messages: list[str] = []
    for item in value:
        if isinstance(item, dict):
            code = str(item.get("code") or "format_warning").strip()
            message = str(item.get("message") or "").strip()
            if code and message:
                messages.append(f"{code}: {message}")
            elif code:
                messages.append(code)
            elif message:
                messages.append(message)
        elif item:
            messages.append(str(item))
    return messages

def _available_user_chars(limit: int, system_prompt: str, *, min_user_prompt_chars: int, user_prompt_reserve_chars: int) -> int:
    reserve = len(system_prompt or "")
    available = limit - reserve
    return max(min_user_prompt_chars, available - user_prompt_reserve_chars)


def _enforce_prompt_limit(step: str, user_prompt: str, system_prompt: str, total_limit: int) -> bool:
    prompt_chars = len(user_prompt) + len(system_prompt)
    if prompt_chars > total_limit:
        logger.warning(
            "%s prompt exceeds soft total limit: total_prompt_chars=%s total_limit=%s; continuing with best-effort request",
            step,
            prompt_chars,
            total_limit,
        )
        return False
    return True


def _add_budget_step(
    trace: dict[str, Any],
    mode: str,
    request_dict: dict[str, Any],
    trim_log: list[str],
) -> None:
    context_metrics = request_dict.get("context_metrics", {}) or {}
    _add_step(
        trace,
        f"{mode}_context_budget",
        {
            "mode": mode,
            "context_metrics": context_metrics,
            "trim_log": trim_log,
        },
    )


def _request_from_trimmed_dict(request_cls: type, payload: dict[str, Any]):
    clean_payload = dict(payload)
    clean_payload.pop("context_metrics", None)
    return request_cls(**clean_payload)




def _derive_trim_steps(before_metrics: dict[str, Any], after_metrics: dict[str, Any], trim_log: list[str]) -> list[str]:
    if trim_log:
        return trim_log
    steps: list[str] = []
    keys = sorted(set(before_metrics) | set(after_metrics))
    for key in keys:
        before_value = before_metrics.get(key)
        after_value = after_metrics.get(key)
        if before_value != after_value:
            steps.append(f"{key}:{before_value}->{after_value}")
    return steps

def _prepare_request_with_budget(
    *,
    request: GenerationRequest | RepairRequest,
    request_cls: type,
    mode: str,
    total_limit: int,
    system_prompt: str,
    trace: dict[str, Any],
    config,
):
    request_dict = asdict(request)
    request_chars_before = len(json.dumps(request_dict, ensure_ascii=False))
    available_user_chars = _available_user_chars(total_limit, system_prompt, min_user_prompt_chars=config.prompt_budget.min_user_prompt_chars, user_prompt_reserve_chars=config.prompt_budget.user_prompt_reserve_chars)
    context_metrics_before = dict(request_dict.get("context_metrics", {}) or {})

    logger.info(
        "%s budget request_id=%s total_prompt_limit=%s system_prompt_chars=%s available_user_prompt_chars=%s request_payload_chars_before=%s",
        mode,
        request.request_id,
        total_limit,
        len(system_prompt),
        available_user_chars,
        request_chars_before,
    )

    request_dict, trim_log = apply_budget_strategy(
        request=request_dict,
        mode=mode,
        request_chars_limit=available_user_chars,
        config=config,
        logger=logger,
    )
    context_metrics_after = dict(request_dict.get("context_metrics", {}) or {})
    trim_steps = _derive_trim_steps(context_metrics_before, context_metrics_after, trim_log)
    typed_request = _request_from_trimmed_dict(request_cls, request_dict)
    request_chars_after = len(json.dumps(request_dict, ensure_ascii=False))
    logger.info(
        "%s budget request_id=%s request_payload_chars_after=%s available_user_prompt_chars=%s trim_steps=%s",
        mode,
        request.request_id,
        request_chars_after,
        available_user_chars,
        trim_steps,
    )
    _add_budget_step(trace, mode, request_dict, trim_steps)
    return typed_request, request_dict, trim_steps, available_user_chars


def _log_prompt_size(
    *,
    request_id: str,
    step: str,
    user_prompt: str,
    system_prompt: str,
    total_prompt_limit: int,
    available_user_prompt_chars: int | None = None,
) -> None:
    logger.info(
        "%s prompt request_id=%s user_prompt_chars=%s system_prompt_chars=%s total_prompt_chars=%s available_user_prompt_chars=%s total_prompt_limit=%s",
        step,
        request_id,
        len(user_prompt),
        len(system_prompt),
        len(user_prompt) + len(system_prompt),
        available_user_prompt_chars,
        total_prompt_limit,
    )


def _call_llm_with_trace(
    *,
    trace: dict[str, Any],
    trace_step: str,
    error_step: str,
    request_id: str,
    client: Any,
    model: str,
    system_prompt: str,
    user_prompt: str,
    think: bool | None,
    config: Any,
    step_name_for_gateway: str,
    parser: Callable[[str], Any],
    extra_payload: dict[str, Any] | None = None,
):
    payload_extra = extra_payload or {}
    raw = None
    meta = None
    try:
        raw, meta = call_model(
            client=client,
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            think=think,
            config=config,
            step=step_name_for_gateway,
        )
        llm_usage = _extract_llm_usage(raw)
        trace['llm_usage'] = _merge_llm_usage(trace.get('llm_usage'), llm_usage)
        try:
            parsed = parser(raw.content)
        except Exception as parse_exc:
            _add_step(
                trace,
                error_step,
                {
                    "meta": _serialize_meta(meta),
                    "prompt": user_prompt,
                    "raw": raw.raw,
                    "content": raw.content,
                    "llm_usage": llm_usage,
                    "error": str(parse_exc),
                    "error_stage": "parse",
                    **payload_extra,
                },
            )
            raise
        _add_step(
            trace,
            trace_step,
            {
                "meta": _serialize_meta(meta),
                "prompt": user_prompt,
                "raw": raw.raw,
                "content": raw.content,
                "parsed": parsed,
                "llm_usage": llm_usage,
                **payload_extra,
            },
        )
        return parsed, raw, meta
    except Exception as exc:
        # Parser failures are already recorded above with raw model output.
        if not trace.get("steps") or trace["steps"][-1].get("step") != error_step:
            payload = {
                "prompt": user_prompt,
                "error": str(exc),
                **payload_extra,
            }
            if raw is not None:
                payload.update({
                    "meta": _serialize_meta(meta),
                    "raw": raw.raw,
                    "content": raw.content,
                    "llm_usage": _extract_llm_usage(raw),
                })
            _add_step(trace, error_step, payload)
        raise




def _extract_llm_usage(raw: Any) -> dict[str, Any]:
    if hasattr(raw, 'usage_dict'):
        usage = raw.usage_dict()
    else:
        usage = {
            'prompt_tokens': int(getattr(raw, 'prompt_tokens', 0) or 0),
            'output_tokens': int(getattr(raw, 'output_tokens', 0) or 0),
            'duration_sec': float(getattr(raw, 'duration_sec', 0.0) or 0.0),
            'total_duration_sec': float(getattr(raw, 'total_duration_sec', 0.0) or 0.0),
            'load_duration_sec': float(getattr(raw, 'load_duration_sec', 0.0) or 0.0),
            'prompt_eval_duration_sec': float(getattr(raw, 'prompt_eval_duration_sec', 0.0) or 0.0),
            'eval_duration_sec': float(getattr(raw, 'eval_duration_sec', 0.0) or 0.0),
        }
        usage['total_tokens'] = usage['prompt_tokens'] + usage['output_tokens']
    return usage


def _merge_llm_usage(existing: dict[str, Any] | None, new_usage: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing or {})
    merged['calls'] = int(merged.get('calls', 0)) + 1
    for key in (
        'prompt_tokens',
        'output_tokens',
        'total_tokens',
        'duration_sec',
        'total_duration_sec',
        'load_duration_sec',
        'prompt_eval_duration_sec',
        'eval_duration_sec',
    ):
        merged[key] = round(float(merged.get(key, 0.0)) + float(new_usage.get(key, 0.0)), 6)
    return merged

def _canonicalize_code_result_for_request(
    parsed: dict[str, Any],
    expected_operation: str | None,
    target_qualname: str | None,
    request_target: dict[str, Any] | None = None,
) -> dict[str, Any]:
    operation = str(parsed.get('operation', '') or '').strip().lower()
    expected = str(expected_operation or '').strip().lower()

    if operation not in {'replace_symbol', 'insert_after_symbol'}:
        raise ValueError(f'Unsupported operation returned by model: {operation}')

    if expected and operation != expected:
        raise ValueError(f'Generator returned operation {operation}, expected {expected}')

    request_target = request_target or {}
    if operation == 'insert_after_symbol':
        parsed['insert_after'] = parsed.get('insert_after') or target_qualname

    parsed['insert_scope'] = parsed.get('insert_scope') or request_target.get('insert_scope')
    parsed['expected_new_symbol_kind'] = (
        parsed.get('expected_new_symbol_kind')
        or request_target.get('expected_new_symbol_kind')
    )
    parsed['parent_qualname'] = parsed.get('parent_qualname') or request_target.get('parent_qualname')
    if not isinstance(parsed.get('import_changes'), list):
        parsed['import_changes'] = []

    return parsed

def _build_generated_code_context(code_artifact: CodeArtifact) -> dict[str, Any]:
    return {
        "operation": code_artifact.operation,
        "target_qualname": code_artifact.target_qualname,
        "target_file": code_artifact.target_file,
        "code": code_artifact.code,
        "insert_after": code_artifact.insert_after,
        "insert_scope": code_artifact.insert_scope,
        "expected_new_symbol_kind": code_artifact.expected_new_symbol_kind,
        "parent_qualname": code_artifact.parent_qualname,
        "import_changes": list(code_artifact.import_changes or []),
    }


def generate(request: GenerationRequest, config_path: str) -> GenerationResult:
    config = load_config(config_path)
    prompts = load_prompts(config)
    client = create_client(config)
    trace = _base_trace(request.request_id, "generate")
    trace_path = build_trace_path(config.trace.output_dir, request.request_id)

    try:
        request, _, _, available_user_chars = _prepare_request_with_budget(
            request=request,
            request_cls=GenerationRequest,
            mode="generate",
            total_limit=config.prompt_budget.generate_chars_limit,
            system_prompt=prompts["system_rules"],
            trace=trace,
            config=config,
        )

        planner_prompt, planner_prompt_metrics = build_planner_user_prompt(
            prompts["planner_user_template"],
            request,
            available_user_chars=available_user_chars,
            default_constraints=config.defaults_constraints,
            runtime_config=config,
        )
        logger.info(
            "planner prompt metrics request_id=%s prompt_chars=%s request_chars=%s module_outline_chars=%s target_chars=%s full_file_chars=%s related_tests_count=%s related_test_chars=%s reference_count=%s reference_chars=%s default_constraints_count=%s",
            request.request_id,
            planner_prompt_metrics.get("planner_prompt_chars"),
            planner_prompt_metrics.get("planner_request_chars"),
            planner_prompt_metrics.get("planner_module_outline_chars"),
            planner_prompt_metrics.get("planner_target_chars"),
            planner_prompt_metrics.get("planner_full_file_chars"),
            planner_prompt_metrics.get("planner_related_tests_count"),
            planner_prompt_metrics.get("planner_related_test_chars"),
            planner_prompt_metrics.get("planner_reference_count"),
            planner_prompt_metrics.get("planner_reference_chars"),
            planner_prompt_metrics.get("planner_default_constraints_count"),
        )
        _log_prompt_size(
            request_id=request.request_id,
            step="planner",
            user_prompt=planner_prompt,
            system_prompt=prompts["system_rules"],
            total_prompt_limit=config.prompt_budget.generate_chars_limit,
            available_user_prompt_chars=available_user_chars,
        )
        _enforce_prompt_limit(
            "planner",
            planner_prompt,
            prompts["system_rules"],
            config.prompt_budget.generate_chars_limit,
        )

        requested_test_mode = str(
            request.options.get("generate_test_mode", config.test_generation_mode)
        )
        logger.info(
            "generate request_id=%s models planner=%s coder=%s test=%s repair=%s test_mode=%s",
            request.request_id,
            config.models.planner_model,
            config.models.coder_model,
            config.models.test_generator_model,
            config.models.repair_model,
            requested_test_mode,
        )

        planner_result, _, _ = _call_llm_with_trace(
            trace=trace,
            trace_step="planner",
            error_step="planner_error",
            request_id=request.request_id,
            client=client,
            model=config.models.planner_model,
            system_prompt=prompts["system_rules"],
            user_prompt=planner_prompt,
            think=config.ollama.think,
            config=config,
            step_name_for_gateway="planner",
            parser=parse_planner_response,
        )

        planner_status = str(planner_result.get("status") or "ok").strip().lower()
        if planner_status in {"needs_planning", "not_enough_context"}:
            reason = str(
                planner_result.get("reason")
                or planner_result.get("message")
                or planner_status
            )
            suggested_next_step = str(planner_result.get("suggested_next_step") or "")
            message = reason
            if suggested_next_step:
                message = f"{reason} Suggested next step: {suggested_next_step}"
            result = GenerationResult(
                request_id=request.request_id,
                status="blocked_by_planner",
                planner_result=planner_result,
                trace_path=str(trace_path),
                llm_usage=trace.get("llm_usage"),
                error_type=planner_status,
                message=message,
            )
            trace["result"] = result.to_dict()
            save_trace(trace_path, trace)
            return result

        coder_prompt, coder_context_metrics = build_coder_user_prompt(
            prompts["coder_user_template"],
            request,
            planner_result,
            config,
            available_user_chars=available_user_chars,
        )
        logger.info(
            "coder context request_id=%s before=%s after=%s target_chars=%s full_file_chars=%s related_test_chars=%s related_tests_count=%s reference_chars=%s reference_count=%s trim_steps=%s",
            request.request_id,
            coder_context_metrics.get("coder_prompt_chars_before_trim"),
            coder_context_metrics.get("coder_prompt_chars_after_trim"),
            coder_context_metrics.get("coder_target_chars"),
            coder_context_metrics.get("coder_full_file_chars"),
            coder_context_metrics.get("coder_related_test_chars"),
            coder_context_metrics.get("related_tests_count"),
            coder_context_metrics.get("coder_reference_chars"),
            coder_context_metrics.get("reference_count"),
            coder_context_metrics.get("coder_trim_steps"),
        )
        logger.info(
            "coder prompt composition request_id=%s mode=%s target_chars=%s module_outline_chars=%s full_file_chars=%s related_tests_count=%s related_test_chars=%s reference_count=%s reference_chars=%s",
            request.request_id,
            getattr(request, 'mode', 'generate'),
            coder_context_metrics.get("coder_target_chars"),
            coder_context_metrics.get("coder_module_outline_chars"),
            coder_context_metrics.get("coder_full_file_chars"),
            coder_context_metrics.get("related_tests_count"),
            coder_context_metrics.get("coder_related_test_chars"),
            coder_context_metrics.get("reference_count"),
            coder_context_metrics.get("coder_reference_chars"),
        )
        _log_prompt_size(
            request_id=request.request_id,
            step="coder",
            user_prompt=coder_prompt,
            system_prompt=prompts["system_rules"],
            total_prompt_limit=config.prompt_budget.generate_chars_limit,
            available_user_prompt_chars=available_user_chars,
        )
        _enforce_prompt_limit(
            "coder",
            coder_prompt,
            prompts["system_rules"],
            config.prompt_budget.generate_chars_limit,
        )

        code_result, _, _ = _call_llm_with_trace(
            trace=trace,
            trace_step="coder",
            error_step="coder_error",
            request_id=request.request_id,
            client=client,
            model=config.models.coder_model,
            system_prompt=prompts["system_rules"],
            user_prompt=coder_prompt,
            think=config.ollama.think,
            config=config,
            step_name_for_gateway="coder",
            parser=parse_code_response,
            extra_payload={"context_metrics": coder_context_metrics},
        )

        code_result = _canonicalize_code_result_for_request(
            code_result,
            request.target.get("operation"),
            request.target.get("qualname"),
            request.target,
        )        

        code_artifact = CodeArtifact(
            operation=code_result["operation"],
            target_qualname=request.target.get("qualname", ""),
            target_file=code_result["target_file"],
            code=code_result["code"],
            insert_after=code_result.get("insert_after"),
            insert_scope=code_result.get("insert_scope"),
            expected_new_symbol_kind=code_result.get("expected_new_symbol_kind"),
            parent_qualname=code_result.get("parent_qualname"),
            import_changes=list(code_result.get("import_changes") or []),
        )

        warnings: list[str] = []
        local_check = validate_russian_error_messages(code_artifact.code)
        if not local_check.get("ok", True):
            warnings.append("generated code contains non-russian ValueError messages")

        test_artifact = None
        mode = str(request.options.get("generate_test_mode", config.test_generation_mode))

        effective_requested_operation = (
            str(request.target.get("operation", "") or "").strip()
            or str(code_artifact.operation or "").strip()
            or "replace_symbol"
        )

        if mode == "always" or (
            mode == "if_missing" and not request.project_context.get("related_tests")
        ):
            request.target["operation"] = effective_requested_operation
                        
            test_request, test_request_dict, _, available_user_chars = _prepare_request_with_budget(
                request=request,
                request_cls=GenerationRequest,
                mode="generate_test",
                total_limit=config.prompt_budget.generate_test_chars_limit,
                system_prompt=prompts["system_rules"],
                trace=trace,
                config=config,
            )

            expected_test_file = build_generated_test_filename(test_request)
            generated_code_context = _build_generated_code_context(code_artifact)

            logger.info(
                "test generation request_id=%s mode=%s expected_test=%s target_source_origin=generated_code_artifact",
                test_request.request_id,
                mode,
                expected_test_file,
            )

            test_planner_prompt, test_planner_metrics = build_test_planner_user_prompt(
                prompts["test_planner_user_template"],
                test_request,
                generated_code_artifact=generated_code_context,
                available_user_chars=available_user_chars,
                default_constraints=config.defaults_constraints,
                planner_result=planner_result,
            )

            test_planner_result, _, _ = _call_llm_with_trace(
                trace=trace,
                trace_step="test_planner",
                error_step="test_planner_error",
                request_id=test_request.request_id,
                client=client,
                model=config.models.planner_model,
                system_prompt=prompts["system_rules"],
                user_prompt=test_planner_prompt,
                think=config.ollama.think,
                config=config,
                step_name_for_gateway="test_planner",
                parser=parse_test_planner_response,
                extra_payload={"context_metrics": test_planner_metrics},
            )
            test_request.test_plan = test_planner_result

            test_prompt, test_context_metrics = build_test_generator_user_prompt(
                template_text=prompts["test_generator_user_template"],
                request=test_request,
                generated_test_file=expected_test_file,
                example_test_source=prompts["test_generator_example_source"],
                runtime_config=config,
                available_user_chars=available_user_chars,
                generated_code_artifact=generated_code_context,
                test_plan=test_request.test_plan,
                planner_result=planner_result,
            )

            logger.info(
                "test generation resolved symbols request_id=%s operation=%s effective_target_symbol=%s anchor_symbol=%s",
                test_request.request_id,
                effective_requested_operation,
                test_context_metrics.get("test_effective_target_symbol"),
               test_context_metrics.get("test_anchor_symbol"),
            )
            logger.info(
                "test generation prompt inputs request_id=%s effective_target_kind=%s effective_target_name=%s generated_code_context_keys=%s",
                test_request.request_id,
                test_context_metrics.get("test_effective_target_kind"),
                test_context_metrics.get("test_effective_target_name"),
                sorted(generated_code_context.keys()),
            )
            logger.info(
                "test generation related context request_id=%s related_tests_count=%s related_test_chars=%s example_included=%s example_chars=%s trim_applied=%s",
                test_request.request_id,
                test_context_metrics.get("test_related_tests_count"),
                test_context_metrics.get("test_related_test_chars"),
                test_context_metrics.get("test_example_included"),
                test_context_metrics.get("test_example_chars"),
                test_context_metrics.get("test_trim_applied"),
            )
            logger.info(
                "test generation prompt budget request_id=%s before=%s after=%s available_user_prompt_chars=%s target_chars=%s request_chars=%s source=%s",
                test_request.request_id,
                test_context_metrics.get("test_prompt_chars_before_trim"),
                test_context_metrics.get("test_prompt_chars_after_trim"),
                available_user_chars,
                test_context_metrics.get("test_target_chars"),
                test_context_metrics.get("test_request_chars"),
                test_context_metrics.get("test_target_source_origin"),
            )

            logger.info(
                "test generation resolved symbols request_id=%s operation=%s effective_target_symbol=%s anchor_symbol=%s",
                test_request.request_id,
                effective_requested_operation,
                test_context_metrics.get("test_effective_target_symbol"),
                test_context_metrics.get("test_anchor_symbol"),
            )
            logger.info(
                "test generation prompt inputs request_id=%s effective_target_kind=%s effective_target_name=%s generated_code_context_keys=%s",
                test_request.request_id,
                test_context_metrics.get("test_effective_target_kind"),
                test_context_metrics.get("test_effective_target_name"),
                sorted(generated_code_context.keys()),
            )            
            logger.info(
                "test_generator context request_id=%s before=%s after=%s target_chars=%s example_chars=%s request_chars=%s related_test_chars=%s related_tests_count=%s source=%s",
                test_request.request_id,
                test_context_metrics.get("test_prompt_chars_before_trim"),
                test_context_metrics.get("test_prompt_chars_after_trim"),
                test_context_metrics.get("test_target_chars"),
                test_context_metrics.get("test_example_chars"),
                test_context_metrics.get("test_request_chars"),
                test_context_metrics.get("test_related_test_chars"),
                test_context_metrics.get("test_related_tests_count"),
                test_context_metrics.get("test_target_source_origin"),
            )

            _log_prompt_size(
                request_id=test_request.request_id,
                step="test_generator",
                user_prompt=test_prompt,
                system_prompt=prompts["system_rules"],
                total_prompt_limit=config.prompt_budget.generate_test_chars_limit,
                available_user_prompt_chars=available_user_chars,
            )
            _enforce_prompt_limit(
                "test_generator",
                test_prompt,
                prompts["system_rules"],
                config.prompt_budget.generate_test_chars_limit,
            )

            test_result, _, _ = _call_llm_with_trace(
                trace=trace,
                trace_step="test_generator",
                error_step="test_generator_error",
                request_id=test_request.request_id,
                client=client,
                model=config.models.test_generator_model,
                system_prompt=prompts["system_rules"],
                user_prompt=test_prompt,
                think=config.ollama.think,
                config=config,
                step_name_for_gateway="test_generator",
                parser=lambda content: parse_test_response(content, expected_test_file),
                extra_payload={
                    "context_metrics": {
                        **(test_request_dict.get("context_metrics", {}) or {}),
                        **test_context_metrics,
                    },
                    "generated_code_context": generated_code_context,
                }
            )
            warnings.extend(_warning_messages_from_format_warnings(test_result.get("format_warnings")))
            test_artifact = TestArtifact(
                file_path=test_result["test_file"],
                source_code=test_result["code"],
            )

        result = GenerationResult(
            request_id=request.request_id,
            status="ok",
            code_artifact=code_artifact,
            test_artifact=test_artifact,
            planner_result=planner_result,
            test_planner_result=(test_request.test_plan if test_artifact is not None else None),
            warnings=warnings,
            trace_path=str(trace_path),
            llm_usage=trace.get('llm_usage'),
        )
        trace["result"] = result.to_dict()
        save_trace(trace_path, trace)
        return result

    except Exception as exc:
        logger.exception("generate failed")
        trace["error"] = {"type": type(exc).__name__, "message": str(exc)}
        save_trace(trace_path, trace)
        return GenerationResult(
            request_id=request.request_id,
            status="error",
            trace_path=str(trace_path),
            llm_usage=trace.get('llm_usage'),
            error_type=type(exc).__name__,
            message=str(exc),
        )


def generate_test(request: GenerationRequest, config_path: str) -> GenerationResult:
    config = load_config(config_path)
    prompts = load_prompts(config)
    client = create_client(config)
    trace = _base_trace(request.request_id, "generate_test")
    trace_path = build_trace_path(config.trace.output_dir, request.request_id)

    try:
        request, request_dict, _, available_user_chars = _prepare_request_with_budget(
            request=request,
            request_cls=GenerationRequest,
            mode="generate_test",
            total_limit=config.prompt_budget.generate_test_chars_limit,
            system_prompt=prompts["system_rules"],
            trace=trace,
            config=config,
        )

        target_source_origin = (
            "generated_code_artifact"
            if request.generated_code_artifact.get("code")
            else "project_context.target_symbol"
        )

        logger.info(
            "generate_test request_id=%s models planner=%s test_generator=%s target_source_origin=%s",
            request.request_id,
            config.models.planner_model,
            config.models.test_generator_model,
            target_source_origin,
        )

        test_planner_prompt, test_planner_metrics = build_test_planner_user_prompt(
            prompts["test_planner_user_template"],
            request,
            generated_code_artifact=request.generated_code_artifact or None,
            available_user_chars=available_user_chars,
            default_constraints=config.defaults_constraints,
        )
        test_planner_result, _, _ = _call_llm_with_trace(
            trace=trace,
            trace_step="test_planner",
            error_step="test_planner_error",
            request_id=request.request_id,
            client=client,
            model=config.models.planner_model,
            system_prompt=prompts["system_rules"],
            user_prompt=test_planner_prompt,
            think=config.ollama.think,
            config=config,
            step_name_for_gateway="test_planner",
            parser=parse_test_planner_response,
            extra_payload={"context_metrics": test_planner_metrics},
        )

        request.test_plan = test_planner_result
        logger.info(
            "generate_test planner_result request_id=%s target_symbol=%s must_use_symbols=%s avoid=%s",
            request.request_id,
            (request.test_plan or {}).get("target_symbol"),
            (request.test_plan or {}).get("must_use_symbols"),
            (request.test_plan or {}).get("avoid"),
        )

        expected_test_file = build_generated_test_filename(request)
        test_prompt, test_context_metrics = build_test_generator_user_prompt(
            template_text=prompts["test_generator_user_template"],
            request=request,
            generated_test_file=expected_test_file,
            example_test_source=prompts["test_generator_example_source"],
            runtime_config=config,
            generated_code_artifact=request.generated_code_artifact or None,
            available_user_chars=available_user_chars,
            test_plan=request.test_plan,
        )

        logger.info(
            "generate_test resolved symbols request_id=%s operation=%s effective_target_symbol=%s anchor_symbol=%s",
            request.request_id,
            (
                str(request.target.get("operation", "") or "").strip()
                or "replace_symbol"
            ),
            test_context_metrics.get("test_effective_target_symbol"),
            test_context_metrics.get("test_anchor_symbol"),
        )
        logger.info(
            "generate_test prompt inputs request_id=%s effective_target_kind=%s effective_target_name=%s generated_code_context_keys=%s",
            request.request_id,
            test_context_metrics.get("test_effective_target_kind"),
            test_context_metrics.get("test_effective_target_name"),
            sorted((request.generated_code_artifact or {}).keys()),
        )
        logger.info(
            "generate_test related context request_id=%s related_tests_count=%s related_test_chars=%s reference_count=%s reference_chars=%s has_reference=%s example_included=%s example_chars=%s trim_applied=%s",
            request.request_id,
            test_context_metrics.get("test_related_tests_count"),
            test_context_metrics.get("test_related_test_chars"),
            test_context_metrics.get("test_reference_count"),
            test_context_metrics.get("test_reference_chars"),
            test_context_metrics.get("test_has_reference_context"),
            test_context_metrics.get("test_example_included"),
            test_context_metrics.get("test_example_chars"),
            test_context_metrics.get("test_trim_applied"),
        )
        logger.info(
            "generate_test prompt budget request_id=%s before=%s after=%s available_user_prompt_chars=%s target_chars=%s request_chars=%s source=%s",
            request.request_id,
            test_context_metrics.get("test_prompt_chars_before_trim"),
            test_context_metrics.get("test_prompt_chars_after_trim"),
            available_user_chars,
            test_context_metrics.get("test_target_chars"),
            test_context_metrics.get("test_request_chars"),
            test_context_metrics.get("test_target_source_origin"),
        )
        logger.info(
            "generate_test context request_id=%s before=%s after=%s target_chars=%s example_chars=%s request_chars=%s source=%s",
            request.request_id,
            test_context_metrics.get("test_prompt_chars_before_trim"),
            test_context_metrics.get("test_prompt_chars_after_trim"),
            test_context_metrics.get("test_target_chars"),
            test_context_metrics.get("test_example_chars"),
            test_context_metrics.get("test_request_chars"),
            test_context_metrics.get("test_target_source_origin"),
        )
        logger.info(
            "generate_test prompt composition request_id=%s related_tests_count=%s related_test_chars=%s reference_count=%s reference_chars=%s",
            request.request_id,
            test_context_metrics.get("test_related_tests_count"),
            test_context_metrics.get("test_related_test_chars"),
            test_context_metrics.get("test_reference_count"),
            test_context_metrics.get("test_reference_chars"),
        )

        _log_prompt_size(
            request_id=request.request_id,
            step="generate_test.test_generator",
            user_prompt=test_prompt,
            system_prompt=prompts["system_rules"],
            total_prompt_limit=config.prompt_budget.generate_test_chars_limit,
            available_user_prompt_chars=available_user_chars,
        )
        _enforce_prompt_limit(
            "generate_test.test_generator",
            test_prompt,
            prompts["system_rules"],
            config.prompt_budget.generate_test_chars_limit,
        )

        test_result, _, _ = _call_llm_with_trace(
            trace=trace,
            trace_step="test_generator",
            error_step="test_generator_error",
            request_id=request.request_id,
            client=client,
            model=config.models.test_generator_model,
            system_prompt=prompts["system_rules"],
            user_prompt=test_prompt,
            think=config.ollama.think,
            config=config,
            step_name_for_gateway="test_generator",
            parser=lambda content: parse_test_response(content, expected_test_file),
            extra_payload={
                "context_metrics": {
                    **(request_dict.get("context_metrics", {}) or {}),
                    **test_context_metrics,
                },
                "generated_code_context": request.generated_code_artifact or None,
            },
        )

        warnings = _warning_messages_from_format_warnings(test_result.get("format_warnings"))
        test_artifact = TestArtifact(
            file_path=test_result["test_file"],
            source_code=test_result["code"],
        )

        result = GenerationResult(
            request_id=request.request_id,
            status="ok",
            test_artifact=test_artifact,
            planner_result=None,
            test_planner_result=request.test_plan,
            warnings=warnings,
            trace_path=str(trace_path),
            llm_usage=trace.get('llm_usage'),
        )
        trace["result"] = result.to_dict()
        save_trace(trace_path, trace)
        return result

    except Exception as exc:
        logger.exception("generate_test failed")
        trace["error"] = {"type": type(exc).__name__, "message": str(exc)}
        save_trace(trace_path, trace)
        return GenerationResult(
            request_id=request.request_id,
            status="error",
            trace_path=str(trace_path),
            llm_usage=trace.get('llm_usage'),
            error_type=type(exc).__name__,
            message=str(exc),
        )


def repair(request: RepairRequest, config_path: str) -> GenerationResult:
    config = load_config(config_path)
    prompts = load_prompts(config)
    client = create_client(config)
    trace = _base_trace(request.request_id, "repair")
    trace_path = build_trace_path(config.trace.output_dir, request.request_id)

    try:
        request, request_dict, _, _ = _prepare_request_with_budget(
            request=request,
            request_cls=RepairRequest,
            mode="repair",
            total_limit=config.prompt_budget.repair_chars_limit,
            system_prompt=prompts["system_rules"],
            trace=trace,
            config=config,
        )

        requested_operation = (
            request.previous_artifact.get("operation")
            or "replace_symbol"
        )

        repair_planner_prompt = build_repair_planner_user_prompt(
            prompts["repair_planner_user_template"],
            request,
            config,
        )
        _log_prompt_size(
            request_id=request.request_id,
            step="repair_planner",
            user_prompt=repair_planner_prompt,
            system_prompt=prompts["system_rules"],
            total_prompt_limit=config.prompt_budget.repair_chars_limit,
        )
        _enforce_prompt_limit(
            "repair_planner",
            repair_planner_prompt,
            prompts["system_rules"],
            config.prompt_budget.repair_chars_limit,
        )
        logger.info(
            "repair planner request_id=%s model=%s",
            request.request_id,
            config.models.planner_model,
        )
        repair_plan, _, _ = _call_llm_with_trace(
            trace=trace,
            trace_step="repair_planner",
            error_step="repair_planner_error",
            request_id=request.request_id,
            client=client,
            model=config.models.planner_model,
            system_prompt=prompts["system_rules"],
            user_prompt=repair_planner_prompt,
            think=config.ollama.think,
            config=config,
            step_name_for_gateway="repair_planner",
            parser=parse_repair_plan_response,
        )
        if str(repair_plan.get("status") or "repairable").strip().lower() == "not_repairable":
            result = GenerationResult(
                request_id=request.request_id,
                status="error",
                planner_result=repair_plan,
                trace_path=str(trace_path),
                llm_usage=trace.get("llm_usage"),
                error_type="not_repairable",
                message=str(repair_plan.get("reason") or repair_plan.get("message") or "not_repairable"),
            )
            trace["result"] = result.to_dict()
            save_trace(trace_path, trace)
            return result

        request.error_context = dict(request.error_context or {})
        request.error_context["repair_plan"] = repair_plan

        repair_prompt = build_repair_user_prompt(
            prompts["repair_user_template"],
            request,
            config,
        )
        _log_prompt_size(
            request_id=request.request_id,
            step="repair",
            user_prompt=repair_prompt,
            system_prompt=prompts["system_rules"],
            total_prompt_limit=config.prompt_budget.repair_chars_limit,
        )
        _enforce_prompt_limit(
            "repair",
            repair_prompt,
            prompts["system_rules"],
            config.prompt_budget.repair_chars_limit,
        )

        logger.info(
            "repair request_id=%s model=%s",
            request.request_id,
            config.models.repair_model,
        )

        repair_result, _, _ = _call_llm_with_trace(
            trace=trace,
            trace_step="repair",
            error_step="repair_error",
            request_id=request.request_id,
            client=client,
            model=config.models.repair_model,
            system_prompt=prompts["system_rules"],
            user_prompt=repair_prompt,
            think=config.ollama.think,
            config=config,
            step_name_for_gateway="repair",
            parser=parse_repair_response,
            extra_payload={"context_metrics": request_dict.get("context_metrics", {})},
        )

        repair_result = _canonicalize_code_result_for_request(
            repair_result,
            requested_operation,
            request.previous_artifact.get("insert_after")
            or request.previous_artifact.get("target_qualname")
            or request.previous_artifact.get("target_symbol"),
            request.previous_artifact,
        )

        code_artifact = CodeArtifact(
            operation=repair_result["operation"],
            target_qualname=request.previous_artifact.get(
                "target_qualname",
                request.previous_artifact.get("target_symbol", ""),
            ),
            target_file=repair_result["target_file"],
            code=repair_result["code"],
            insert_after=repair_result.get("insert_after"),
            insert_scope=repair_result.get("insert_scope"),
            expected_new_symbol_kind=repair_result.get("expected_new_symbol_kind"),
            parent_qualname=repair_result.get("parent_qualname"),
            import_changes=list(repair_result.get("import_changes") or []),
        )

        result = GenerationResult(
            request_id=request.request_id,
            status="ok",
            code_artifact=code_artifact,
            trace_path=str(trace_path),
            llm_usage=trace.get('llm_usage'),
        )
        trace["result"] = result.to_dict()
        save_trace(trace_path, trace)
        return result

    except Exception as exc:
        logger.exception("repair failed")
        trace["error"] = {"type": type(exc).__name__, "message": str(exc)}
        save_trace(trace_path, trace)
        return GenerationResult(
            request_id=request.request_id,
            status="error",
            trace_path=str(trace_path),
            llm_usage=trace.get('llm_usage'),
            error_type=type(exc).__name__,
            message=str(exc),
        )





_REVIEW_LIST_FIELDS = {'reasons', 'production_risks', 'test_issues', 'next_steps'}
_REVIEW_ALLOWED_VERDICTS = {
    'production_likely_ok_test_likely_bad',
    'production_likely_bad_test_valid',
    'both_uncertain',
    'environment_or_import_issue',
    'insufficient_context',
}
_REVIEW_ALLOWED_KEEP = {'yes', 'no', 'manual_review'}
_REVIEW_ALLOWED_ACTIONS = {
    'keep_production_code_exclude_test',
    'reject_production_code',
    'manual_review',
    'rerun_test_generation',
}


def _as_review_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    return [value]



def _strip_single_json_markdown_fence(text: str) -> tuple[str, bool]:
    stripped = (text or '').strip()
    if not stripped.startswith('```') or not stripped.endswith('```'):
        return text, False
    lines = stripped.splitlines()
    if len(lines) < 3:
        return text, False
    opening = lines[0].strip()
    closing = lines[-1].strip()
    if not opening.startswith('```') or closing != '```':
        return text, False
    language = opening[3:].strip().lower()
    if language and language != 'json':
        return text, False
    inner = '\n'.join(lines[1:-1]).strip()
    if not inner.startswith('{') or not inner.endswith('}'):
        return text, False
    return inner, True


def _parse_generated_test_review_response(content: str) -> dict[str, Any]:
    try:
        return parse_json_object(content)
    except ValueError as original_exc:
        unfenced, stripped_fence = _strip_single_json_markdown_fence(content)
        if not stripped_fence:
            raise
        try:
            data = parse_json_object(unfenced)
        except Exception:
            raise original_exc
        diagnostics = data.get('_diagnostics') if isinstance(data.get('_diagnostics'), dict) else {}
        diagnostics = dict(diagnostics)
        diagnostics['json_markdown_fence_stripped'] = True
        diagnostics['json_contract_warning'] = 'Модель вернула JSON внутри markdown-блока; fence был снят перед parsing без изменения JSON-содержимого.'
        data['_diagnostics'] = diagnostics
        format_warnings = data.get('format_warnings') if isinstance(data.get('format_warnings'), list) else []
        format_warnings = list(format_warnings)
        format_warnings.append({
            'code': 'review_json_markdown_fence_stripped',
            'message': 'Модель вернула review JSON внутри markdown-блока; wrapper был снят перед parsing.',
        })
        data['format_warnings'] = format_warnings
        return data


def _normalize_generated_test_review(review: Any) -> dict[str, Any]:
    """Return a stable advisory-review payload for codecollector/codeui.

    Models sometimes return scalar strings for list fields or slightly
    inconsistent enum combinations. Normalize the machine contract without
    changing the review into an automatic decision.
    """
    if not isinstance(review, dict):
        return {
            'verdict': 'insufficient_context',
            'confidence': 0.0,
            'production_code_quality': '',
            'generated_test_quality': '',
            'should_keep_production_code': 'manual_review',
            'recommended_action': 'manual_review',
            'reasons': ['Модель вернула review не в объектном JSON-формате.'],
            'production_risks': [],
            'test_issues': [],
            'recommendation_summary': 'Review недоступен: модель вернула не объектный JSON.',
            'next_steps': ['Повторить review или проверить production/test вручную.'],
        }

    normalized = dict(review)
    for field in _REVIEW_LIST_FIELDS:
        normalized[field] = _as_review_list(normalized.get(field))

    verdict = str(normalized.get('verdict') or '').strip()
    if verdict not in _REVIEW_ALLOWED_VERDICTS:
        verdict = 'both_uncertain'
    normalized['verdict'] = verdict

    raw_confidence = normalized.get('confidence')
    confidence_map = {
        'low': 0.3,
        'medium': 0.6,
        'high': 0.9,
        'низкая': 0.3,
        'средняя': 0.6,
        'высокая': 0.9,
    }
    if isinstance(raw_confidence, str):
        confidence_key = raw_confidence.strip().lower()
        confidence = confidence_map.get(confidence_key)
    else:
        confidence = None
    if confidence is None:
        try:
            confidence = float(raw_confidence or 0.0)
        except Exception:
            confidence = 0.0
    normalized['confidence'] = max(0.0, min(1.0, confidence))

    keep = str(normalized.get('should_keep_production_code') or '').strip()
    if keep not in _REVIEW_ALLOWED_KEEP:
        keep = 'manual_review'
    action = str(normalized.get('recommended_action') or '').strip()
    if action not in _REVIEW_ALLOWED_ACTIONS:
        action = 'manual_review'

    production_risks = normalized.get('production_risks') or []
    test_issues = normalized.get('test_issues') or []
    combined_issue_text = ' '.join(str(item).lower() for item in [*normalized.get('reasons', []), *test_issues])
    constructor_or_call_issue = any(
        marker in combined_issue_text
        for marker in (
            'missing required positional argument',
            'missing required keyword-only argument',
            'required positional argument',
            'обязательн',
            'конструктор',
            'constructor',
            '__init__',
        )
    )
    if (
        constructor_or_call_issue
        and not production_risks
        and verdict == 'environment_or_import_issue'
    ):
        verdict = 'production_likely_ok_test_likely_bad'
        normalized['verdict'] = verdict
        keep = 'yes'
        action = 'keep_production_code_exclude_test'

    if production_risks and keep == 'yes':
        keep = 'manual_review'
    if production_risks and action == 'keep_production_code_exclude_test':
        action = 'manual_review'

    normalized['should_keep_production_code'] = keep
    normalized['recommended_action'] = action
    for field in ('production_code_quality', 'generated_test_quality', 'recommendation_summary'):
        normalized[field] = str(normalized.get(field) or '')
    if not normalized.get('recommendation_summary'):
        if action == 'keep_production_code_exclude_test':
            normalized['recommendation_summary'] = 'Production-код можно оставить для ручного merge review; generated test лучше исключить или перегенерировать.'
        elif action == 'reject_production_code':
            normalized['recommendation_summary'] = 'Production-код лучше отклонить: review нашел риск в основном коде.'
        elif action == 'rerun_test_generation':
            normalized['recommendation_summary'] = 'Production-код требует ручной проверки; generated test лучше перегенерировать.'
        else:
            normalized['recommendation_summary'] = 'Требуется ручная проверка production-кода и generated test.'
    if not normalized.get('next_steps'):
        if action == 'keep_production_code_exclude_test':
            normalized['next_steps'] = ['Оставить production-код на ручной merge review.', 'Исключить текущий generated test.', 'Перегенерировать тест с учетом test_issues.']
        elif action == 'reject_production_code':
            normalized['next_steps'] = ['Отклонить production-код.', 'Исправить production generation или repair prompt.', 'Повторить запуск.']
        elif action == 'rerun_test_generation':
            normalized['next_steps'] = ['Оставить production-код только после ручной проверки.', 'Перегенерировать generated test.', 'Проверить новый тест по verification context.']
        else:
            normalized['next_steps'] = ['Проверить production diff вручную.', 'Проверить generated test вручную или перегенерировать его.']
    return normalized


def review_generated_test_failure(request: dict[str, Any], config_path: str) -> dict[str, Any]:
    config = load_config(config_path)
    prompts = load_prompts(config)
    client = create_client(config)
    request_id = str(request.get('request_id') or 'review-generated-test-failure')
    trace = _base_trace(request_id, 'review_generated_test_failure')
    trace_path = build_trace_path(config.trace.output_dir, request_id)
    try:
        template = prompts.get('generated_test_review_user_template') or ''
        builder = GeneratedTestFailureReviewPromptBuilder(template)
        user_prompt, metrics = builder.build(request)
        _log_prompt_size(
            request_id=request_id,
            step='generated_test_review',
            user_prompt=user_prompt,
            system_prompt=prompts['system_rules'],
            total_prompt_limit=config.prompt_budget.repair_chars_limit,
        )
        parsed, raw, _meta = _call_llm_with_trace(
            trace=trace,
            trace_step='generated_test_review',
            error_step='generated_test_review_error',
            request_id=request_id,
            client=client,
            model=config.models.repair_model,
            system_prompt=prompts['system_rules'],
            user_prompt=user_prompt,
            think=config.ollama.think,
            config=config,
            step_name_for_gateway='generated_test_review',
            parser=_parse_generated_test_review_response,
            extra_payload={'prompt_metrics': metrics},
        )
        parsed = _normalize_generated_test_review(parsed)
        trace['normalized_review'] = parsed
        if config.trace.save_to_file:
            trace_path.parent.mkdir(parents=True, exist_ok=True)
            trace_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding='utf-8')
        return {
            'request_id': request_id,
            'status': 'ok',
            'review': parsed,
            'trace_path': str(trace_path),
            'llm_usage': trace.get('llm_usage') or {},
            'format_warnings': parsed.get('format_warnings') if isinstance(parsed, dict) else [],
            'error_type': None,
            'message': None,
        }
    except Exception as exc:
        if config.trace.save_to_file:
            trace_path.parent.mkdir(parents=True, exist_ok=True)
            trace_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding='utf-8')
        return {
            'request_id': request_id,
            'status': 'error',
            'review': None,
            'trace_path': str(trace_path),
            'llm_usage': trace.get('llm_usage') or {},
            'error_type': type(exc).__name__,
            'message': str(exc),
        }

# codegenerator/orchestration/generation_service.py
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Callable

from codegenerator.config import load_config
from codegenerator.context.budget import apply_budget_strategy
from codegenerator.generation.coder import parse_code_response
from codegenerator.generation.planner import parse_planner_response
from codegenerator.generation.repair import parse_repair_response
from codegenerator.generation.test_generator import (
    build_generated_test_filename,
    parse_test_response,
)
from codegenerator.llm.gateway import call_model, create_client
from codegenerator.logger import get_logger
from codegenerator.models.artifacts import CodeArtifact, TestArtifact
from codegenerator.models.requests import GenerationRequest, RepairRequest
from codegenerator.models.results import GenerationResult
from codegenerator.prompts.prompt_builder import (
    build_coder_user_prompt,
    build_planner_user_prompt,
    build_repair_user_prompt,
    build_test_generator_user_prompt,
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


def _available_user_chars(limit: int, system_prompt: str) -> int:
    reserve = len(system_prompt or "")
    available = limit - reserve
    return max(400, available - 100)


def _enforce_prompt_limit(step: str, prompt: str, limit: int) -> None:
    prompt_chars = len(prompt)
    if prompt_chars > limit:
        raise ValueError(
            f"{step} prompt exceeds limit: prompt_chars={prompt_chars} limit={limit}"
        )


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


def _prepare_request_with_budget(
    *,
    request: GenerationRequest | RepairRequest,
    request_cls: type,
    mode: str,
    total_limit: int,
    system_prompt: str,
    trace: dict[str, Any],
):
    request_dict = asdict(request)
    available_user_chars = _available_user_chars(total_limit, system_prompt)

    logger.info(
        "%s budget request_id=%s total_limit=%s system_chars=%s available_user_chars=%s",
        mode,
        request.request_id,
        total_limit,
        len(system_prompt),
        available_user_chars,
    )

    request_dict, trim_log = apply_budget_strategy(
        request=request_dict,
        mode=mode,
        request_chars_limit=available_user_chars,
        logger=logger,
    )
    typed_request = _request_from_trimmed_dict(request_cls, request_dict)
    _add_budget_step(trace, mode, request_dict, trim_log)
    return typed_request, request_dict, trim_log, available_user_chars


def _log_prompt_size(
    *,
    request_id: str,
    step: str,
    user_prompt: str,
    system_prompt: str,
    limit: int,
) -> None:
    logger.info(
        "%s prompt request_id=%s user_prompt_chars=%s system_prompt_chars=%s total_prompt_chars=%s limit=%s",
        step,
        request_id,
        len(user_prompt),
        len(system_prompt),
        len(user_prompt) + len(system_prompt),
        limit,
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
        parsed = parser(raw.content)
        _add_step(
            trace,
            trace_step,
            {
                "meta": _serialize_meta(meta),
                "prompt": user_prompt,
                "raw": raw.raw,
                "content": raw.content,
                "parsed": parsed,
                **payload_extra,
            },
        )
        return parsed, raw, meta
    except Exception as exc:
        _add_step(
            trace,
            error_step,
            {
                "prompt": user_prompt,
                "error": str(exc),
                **payload_extra,
            },
        )
        raise


def _build_generated_code_context(code_artifact: CodeArtifact) -> dict[str, Any]:
    return {
        "operation": code_artifact.operation,
        "target_qualname": code_artifact.target_qualname,
        "target_file": code_artifact.target_file,
        "code": code_artifact.code,
        "insert_after": code_artifact.insert_after,
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
        )

        planner_prompt = build_planner_user_prompt(
            prompts["planner_user_template"],
            request,
            config.defaults_constraints,
        )
        _log_prompt_size(
            request_id=request.request_id,
            step="planner",
            user_prompt=planner_prompt,
            system_prompt=prompts["system_rules"],
            limit=config.prompt_budget.generate_chars_limit,
        )
        _enforce_prompt_limit(
            "planner",
            planner_prompt,
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

        coder_prompt, coder_context_metrics = build_coder_user_prompt(
            prompts["coder_user_template"],
            request,
            planner_result,
            config,
            available_user_chars=available_user_chars,
        )
        logger.info(
            "coder context request_id=%s before=%s after=%s target_chars=%s full_file_chars=%s reference_chars=%s references=%s",
            request.request_id,
            coder_context_metrics.get("coder_prompt_chars_before_trim"),
            coder_context_metrics.get("coder_prompt_chars_after_trim"),
            coder_context_metrics.get("coder_target_chars"),
            coder_context_metrics.get("coder_full_file_chars"),
            coder_context_metrics.get("coder_reference_chars"),
            coder_context_metrics.get("reference_count"),
        )
        _log_prompt_size(
            request_id=request.request_id,
            step="coder",
            user_prompt=coder_prompt,
            system_prompt=prompts["system_rules"],
            limit=available_user_chars,
        )
        _enforce_prompt_limit(
            "coder",
            coder_prompt,
            available_user_chars,
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

        code_artifact = CodeArtifact(
            operation=code_result["operation"],
            target_qualname=request.target.get("qualname", ""),
            target_file=code_result["target_file"],
            code=code_result["code"],
            insert_after=code_result.get("insert_after"),
        )

        warnings: list[str] = []
        local_check = validate_russian_error_messages(code_artifact.code)
        if not local_check.get("ok", True):
            warnings.append("generated code contains non-russian ValueError messages")

        test_artifact = None
        mode = str(request.options.get("generate_test_mode", config.test_generation_mode))
        if mode == "always" or (
            mode == "if_missing" and not request.project_context.get("related_tests")
        ):
            test_request, test_request_dict, _, available_user_chars = _prepare_request_with_budget(
                request=request,
                request_cls=GenerationRequest,
                mode="generate_test",
                total_limit=config.prompt_budget.generate_test_chars_limit,
                system_prompt=prompts["system_rules"],
                trace=trace,
            )

            expected_test_file = build_generated_test_filename(test_request)
            generated_code_context = _build_generated_code_context(code_artifact)

            logger.info(
                "test generation request_id=%s mode=%s expected_test=%s target_source_origin=generated_code_artifact",
                test_request.request_id,
                mode,
                expected_test_file,
            )

            test_prompt, test_context_metrics = build_test_generator_user_prompt(
                template_text=prompts["test_generator_user_template"],
                request=test_request,
                generated_test_file=expected_test_file,
                example_test_source=prompts["test_generator_example_source"],
                runtime_config=config,
                available_user_chars=available_user_chars,
                generated_code_artifact=generated_code_context,
            )

            logger.info(
                "test_generator context request_id=%s before=%s after=%s target_chars=%s example_chars=%s request_chars=%s source=%s",
                test_request.request_id,
                test_context_metrics.get("test_prompt_chars_before_trim"),
                test_context_metrics.get("test_prompt_chars_after_trim"),
                test_context_metrics.get("test_target_chars"),
                test_context_metrics.get("test_example_chars"),
                test_context_metrics.get("test_request_chars"),
                test_context_metrics.get("test_target_source_origin"),
            )

            _log_prompt_size(
                request_id=test_request.request_id,
                step="test_generator",
                user_prompt=test_prompt,
                system_prompt=prompts["system_rules"],
                limit=config.prompt_budget.generate_test_chars_limit,
            )
            _enforce_prompt_limit(
                "test_generator",
                test_prompt,
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
            warnings=warnings,
            trace_path=str(trace_path),
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
        )

        target_source_origin = (
            "generated_code_artifact"
            if request.generated_code_artifact.get("code")
            else "project_context.target_symbol"
        )

        logger.info(
            "generate_test request_id=%s model=%s planner=skipped target_source_origin=%s",
            request.request_id,
            config.models.test_generator_model,
            target_source_origin,
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

        _log_prompt_size(
            request_id=request.request_id,
            step="generate_test.test_generator",
            user_prompt=test_prompt,
            system_prompt=prompts["system_rules"],
            limit=config.prompt_budget.generate_test_chars_limit,
        )
        _enforce_prompt_limit(
            "generate_test.test_generator",
            test_prompt,
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

        test_artifact = TestArtifact(
            file_path=test_result["test_file"],
            source_code=test_result["code"],
        )

        result = GenerationResult(
            request_id=request.request_id,
            status="ok",
            test_artifact=test_artifact,
            planner_result=None,
            trace_path=str(trace_path),
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
        )

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
            limit=config.prompt_budget.repair_chars_limit,
        )
        _enforce_prompt_limit(
            "repair",
            repair_prompt,
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

        code_artifact = CodeArtifact(
            operation=repair_result["operation"],
            target_qualname=request.previous_artifact.get(
                "target_qualname",
                request.previous_artifact.get("target_symbol", ""),
            ),
            target_file=repair_result["target_file"],
            code=repair_result["code"],
            insert_after=repair_result.get("insert_after"),
        )

        result = GenerationResult(
            request_id=request.request_id,
            status="ok",
            code_artifact=code_artifact,
            trace_path=str(trace_path),
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
            error_type=type(exc).__name__,
            message=str(exc),
        )
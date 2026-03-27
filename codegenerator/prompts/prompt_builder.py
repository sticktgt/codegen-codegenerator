# codegenerator/prompts/prompt_builder.py
from __future__ import annotations

import json
from typing import Any

from codegenerator.config import RuntimeConfig
from codegenerator.models.requests import GenerationRequest, RepairRequest


def _pretty(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def merged_constraints(
    req_constraints: list[str],
    default_constraints: list[str],
) -> list[str]:
    out: list[str] = []
    for item in [*default_constraints, *req_constraints]:
        if item and item not in out:
            out.append(item)
    return out


def _truncate_text(value: str, limit: int) -> tuple[str, bool]:
    if limit <= 0 or len(value) <= limit:
        return value, False
    return value[: max(0, limit - 24)] + "\n# ... truncated ...", True


def _reference_text_chars(value: str) -> int:
    return 0 if value == "none" else len(value)


def _render_module_outline(module_outline: list[dict[str, Any]]) -> str:
    if not module_outline:
        return "[]"
    lines: list[str] = []
    for item in module_outline[:12]:
        qualname = item.get("qualname", "")
        kind = item.get("kind", "")
        name = item.get("name", "")
        doc = (item.get("docstring", "") or "").strip().replace("\n", " ")
        suffix = f" — {doc[:120]}" if doc else ""
        lines.append(f"- [{kind}] {qualname or name}{suffix}")
    return "\n".join(lines)


def _render_target_symbol(target_symbol: dict[str, Any]) -> str:
    source = (target_symbol.get("source") or "").strip()
    if source:
        return source
    return _pretty({k: v for k, v in target_symbol.items() if k != "source"})


def _render_reference_artifacts(
    reference_context: dict[str, Any],
    max_items: int,
    per_item_chars: int,
) -> tuple[str, dict[str, Any]]:
    artifacts = list(reference_context.get("reference_artifacts") or [])[:max_items]
    blocks: list[str] = []
    total_chars = 0
    titles: list[str] = []
    content_modes: list[str] = []

    for item in artifacts:
        raw_content = str(item.get("content", ""))
        if per_item_chars > 0 and len(raw_content) > per_item_chars:
            continue
        content = raw_content
        title = str(item.get("title", ""))
        usage_mode = str(item.get("usage_mode", ""))
        block = f"Title: {title}\nUsage mode: {usage_mode}\nCode:\n{content}"
        blocks.append(block)
        titles.append(title)
        content_modes.append(str(item.get("content_mode", "")))
        total_chars += len(content)

    rendered = "\n\n---\n\n".join(blocks) if blocks else "none"
    metrics = {
        "reference_count": len(artifacts),
        "reference_chars": total_chars,
        "reference_titles": titles,
        "reference_content_modes": content_modes,
    }
    return rendered, metrics


def _build_coder_prompt_metrics(
    prompt: str,
    target_text: str,
    full_file_text: str,
    reference_text: str,
    before_trim: int,
    after_trim: int,
) -> dict[str, Any]:
    return {
        "coder_prompt_chars_before_trim": before_trim,
        "coder_prompt_chars_after_trim": after_trim,
        "coder_target_chars": len(target_text),
        "coder_full_file_chars": len(full_file_text),
        "coder_reference_chars": _reference_text_chars(reference_text),
    }


def _render_constraints_block(constraints: list[str], limit: int = 6) -> str:
    if not constraints:
        return "[]"
    return "\n".join(f"- {item}" for item in constraints[:limit])


def _compact_change_request_for_codegen(
    change_request: dict[str, Any],
    planner_result: dict[str, Any] | None = None,
) -> str:
    title = str(change_request.get("title", "") or "").strip()
    description = str(change_request.get("description", "") or "").strip()
    constraints = [str(item) for item in (change_request.get("constraints") or []) if item]

    lines: list[str] = []

    if title:
        lines.append(f"Title: {title}")

    if planner_result:
        intent_summary = str(planner_result.get("intent_summary", "") or "").strip()
        if intent_summary:
            lines.append(f"Planned intent: {intent_summary}")

        planner_constraints = [
            str(item) for item in (planner_result.get("constraints") or []) if item
        ]
        if planner_constraints:
            lines.append("Planner constraints:")
            lines.extend(f"- {item}" for item in planner_constraints[:8])
        elif constraints:
            lines.append("Request constraints:")
            lines.extend(f"- {item}" for item in constraints[:6])
    else:
        if description:
            description_short, _ = _truncate_text(description, 700)
            lines.append("Description:")
            lines.append(description_short)
        if constraints:
            lines.append("Constraints:")
            lines.extend(f"- {item}" for item in constraints[:8])

    return "\n".join(lines).strip()


def build_planner_user_prompt(
    template_text: str,
    request: GenerationRequest,
    default_constraints: list[str],
) -> str:
    cr = request.change_request
    target = request.target
    constraints = merged_constraints(cr.get("constraints", []), default_constraints)

    request_text = ((cr.get("title", "") + "\n" + cr.get("description", "")).strip())

    return template_text.format(
        experiment_name=request.request_id,
        operation=target.get("operation", "replace_symbol"),
        target_file=target.get("file_path", ""),
        target_symbol=target.get("qualname", ""),
        insert_after=target.get("insert_after") or "null",
        reference_symbol="null",
        request=request_text,
    ) + "\n\nОграничения:\n" + _pretty(constraints)


def build_coder_user_prompt(
    template_text: str,
    request: GenerationRequest,
    planner_result: dict[str, Any],
    runtime_config: RuntimeConfig,
    available_user_chars: int | None = None,
) -> tuple[str, dict[str, Any]]:
    pc = request.project_context or {}
    module_outline_text = _render_module_outline(pc.get("module_outline", []))
    target_text = _render_target_symbol(
        pc.get("target_symbol") or pc.get("target_function") or {}
    )
    full_file_text = str(pc.get("full_file_source", "") or "")

    if runtime_config.coder_max_full_file_chars <= 0:
        full_file_text = ""
    else:
        full_file_text, _ = _truncate_text(
            full_file_text,
            runtime_config.coder_max_full_file_chars,
        )

    reference_text, ref_metrics = _render_reference_artifacts(
        request.reference_context or {},
        runtime_config.coder_max_reference_artifacts,
        runtime_config.coder_max_reference_chars,
    )

    compact_request_text = _compact_change_request_for_codegen(
        request.change_request,
        planner_result,
    )

    def _render(
        module_outline_value: str,
        target_value: str,
        full_file_value: str,
        reference_value: str,
        request_value: str,
    ) -> str:
        return template_text.format(
            operation=request.target.get("operation", "replace_symbol"),
            target_file=request.target.get("file_path", ""),
            target_symbol=request.target.get("qualname", ""),
            insert_after=request.target.get("insert_after") or "null",
            reference_symbol="null",
            planner_json=_pretty(planner_result),
            request=request_value,
            module_outline=module_outline_value,
            target_function=target_value,
            reference_function=reference_value,
            full_file_source=full_file_value,
        )

    initial_prompt = _render(
        module_outline_text,
        target_text,
        full_file_text,
        reference_text,
        compact_request_text,
    )
    before_trim = len(initial_prompt)

    if len(initial_prompt) > runtime_config.coder_prompt_target_chars and full_file_text:
        full_file_text = ""
    prompt = _render(
        module_outline_text,
        target_text,
        full_file_text,
        reference_text,
        compact_request_text,
    )

    if len(prompt) > runtime_config.coder_prompt_target_chars and reference_text != "none":
        reference_text = "none"
        ref_metrics = {
            **ref_metrics,
            "reference_count": 0,
            "reference_chars": 0,
            "reference_titles": [],
            "reference_content_modes": [],
        }
        prompt = _render(
            module_outline_text,
            target_text,
            full_file_text,
            reference_text,
            compact_request_text,
        )

    if len(prompt) > runtime_config.coder_prompt_target_chars:
        module_outline_text, _ = _truncate_text(module_outline_text, 400)
        prompt = _render(
            module_outline_text,
            target_text,
            full_file_text,
            reference_text,
            compact_request_text,
        )

    if len(prompt) > runtime_config.coder_prompt_hard_limit:
        target_text, _ = _truncate_text(
            target_text,
            max(220, runtime_config.coder_prompt_hard_limit // 4),
        )
        prompt = _render(
            module_outline_text,
            target_text,
            full_file_text,
            reference_text,
            compact_request_text,
        )

    if len(prompt) > runtime_config.coder_prompt_hard_limit and reference_text != "none":
        reference_text = "none"
        ref_metrics = {
            **ref_metrics,
            "reference_count": 0,
            "reference_chars": 0,
            "reference_titles": [],
            "reference_content_modes": [],
        }
        prompt = _render(
            module_outline_text,
            target_text,
            full_file_text,
            reference_text,
            compact_request_text,
        )

    runtime_limit = available_user_chars or runtime_config.coder_prompt_hard_limit

    if len(prompt) > runtime_limit and reference_text != "none":
        reference_text = "none"
        ref_metrics = {
            **ref_metrics,
            "reference_count": 0,
            "reference_chars": 0,
            "reference_titles": [],
            "reference_content_modes": [],
        }
        prompt = _render(
            module_outline_text,
            target_text,
            full_file_text,
            reference_text,
            compact_request_text,
        )

    if len(prompt) > runtime_limit and module_outline_text != "[]":
        module_outline_text, _ = _truncate_text(module_outline_text, 180)
        prompt = _render(
            module_outline_text,
            target_text,
            full_file_text,
            reference_text,
            compact_request_text,
        )

    if len(prompt) > runtime_limit:
        compact_request_text, _ = _truncate_text(
            compact_request_text,
            max(220, runtime_limit // 5),
        )
        prompt = _render(
            module_outline_text,
            target_text,
            full_file_text,
            reference_text,
            compact_request_text,
        )

    if len(prompt) > runtime_limit:
        target_text, _ = _truncate_text(
            target_text,
            max(220, runtime_limit // 4),
        )
        prompt = _render(
            module_outline_text,
            target_text,
            full_file_text,
            reference_text,
            compact_request_text,
        )

    metrics = _build_coder_prompt_metrics(
        prompt,
        target_text,
        full_file_text,
        reference_text,
        before_trim,
        len(prompt),
    )
    metrics.update(ref_metrics)
    return prompt, metrics


def build_repair_user_prompt(
    template_text: str,
    request: RepairRequest,
    runtime_config: RuntimeConfig | None = None,
) -> str:
    project_context = request.project_context or {}
    target_symbol = project_context.get("target_symbol") or {}
    module_outline = project_context.get("module_outline", [])
    full_file_source = str(project_context.get("full_file_source", "") or "")
    change_request = request.change_request or {}

    change_request_text = _compact_change_request_for_codegen(change_request, None)
    constraints = [str(item) for item in (change_request.get("constraints") or []) if item]

    target_source = str(target_symbol.get("source", "") or "")
    target_source, _ = _truncate_text(target_source, 900)
    module_outline_text = _render_module_outline(module_outline)

    previous_code = str(request.previous_artifact.get("code", "") or "")
    previous_code, _ = _truncate_text(previous_code, 1200)

    if runtime_config and runtime_config.coder_max_full_file_chars <= 0:
        full_file_source = ""
    elif full_file_source:
        full_file_source, _ = _truncate_text(full_file_source, 700)

    reference_context = request.reference_context or {}
    compact_reference = {
        "reference_summary": reference_context.get("reference_summary", {}),
        "reference_artifacts": [
            {
                "title": item.get("title", ""),
                "usage_mode": item.get("usage_mode", ""),
                "content_mode": item.get("content_mode", ""),
                "content": _truncate_text(
                    str(item.get("content", "") or ""),
                    (runtime_config.repair_max_reference_chars if runtime_config else 420),
                )[0],
            }
            for item in list(reference_context.get("reference_artifacts") or [])[:1]
        ],
    }

    target_rendered = target_source or _pretty(
        {k: v for k, v in target_symbol.items() if k != "source"}
    )

    values = {
        "operation": request.previous_artifact.get("operation", "replace_symbol"),
        "target_file": request.previous_artifact.get("target_file", ""),
        "target_symbol": request.previous_artifact.get(
            "target_qualname",
            request.previous_artifact.get("target_symbol", ""),
        ),
        "insert_after": request.previous_artifact.get("insert_after") or "null",
        "request": change_request_text or "repair request",
        "planner_json": _pretty(
            {
                "repair_for": request.previous_generation_request_id,
                "change_request": change_request,
            }
        ),
        "verification_summary": _pretty(request.error_context),
        "verification_summary_json": _pretty(request.error_context),
        "module_outline": module_outline_text,
        "target_function": target_rendered,
        "full_file_source": full_file_source,
        "current_generated_code": previous_code,
        "module_outline_block": (
            "\n\nModule outline:\n" + module_outline_text if module_outline_text else ""
        ),
        "target_function_block": (
            "\n\nTarget function:\n" + target_rendered if target_rendered else ""
        ),
        "reference_function_block": "",
        "full_file_source_block": (
            "\n\nFull file source:\n" + full_file_source if full_file_source else ""
        ),
    }

    extra = [
        "Change request to preserve:",
        change_request_text or "repair request",
        "",
        "Constraints:",
        _render_constraints_block(constraints),
        "",
        "Repair instruction:",
        "Fix the generated code so it becomes valid and keeps the requested change. Do not revert to the original implementation and do not weaken the requested behavior.",
        "",
        "Reference context:",
        _pretty(compact_reference),
    ]

    prompt = template_text.format(**values) + "\n\n" + "\n".join(extra)

    if runtime_config and len(prompt) > runtime_config.repair_prompt_hard_limit:
        compact_reference["reference_artifacts"] = []
        extra[-1] = _pretty(compact_reference)
        prompt = template_text.format(**values) + "\n\n" + "\n".join(extra)

    if runtime_config and len(prompt) > runtime_config.repair_prompt_hard_limit:
        values["module_outline_block"] = ""
        values["full_file_source_block"] = ""
        prompt = template_text.format(**values) + "\n\n" + "\n".join(extra)

    return prompt


def build_test_generator_user_prompt(
    template_text: str,
    request: GenerationRequest,
    generated_test_file: str,
    example_test_source: str,
    runtime_config: RuntimeConfig,
    available_user_chars: int,
    generated_code_artifact: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    pc = request.project_context or {}
    target_symbol = pc.get("target_symbol") or {}

    compact_request_text = _compact_change_request_for_codegen(
        request.change_request,
        planner_result=None,
    )

    if generated_code_artifact and generated_code_artifact.get("code"):
        target_source = str(generated_code_artifact.get("code", "")).strip()
        target_source_origin = "generated_code_artifact"
    else:
        target_source = str(target_symbol.get("source", "") or "").strip()
        target_source_origin = "project_context.target_symbol"

    example_text, _ = _truncate_text(example_test_source or "", 700)

    def _render(
        *,
        request_value: str,
        target_function_value: str,
        example_value: str,
    ) -> str:
        example_block = f"\n\nExample test:\n{example_value}" if example_value else ""
        target_block = (
            f"\n\nGenerated target code:\n{target_function_value}"
            if target_function_value
            else ""
        )
        return template_text.format(
            operation=request.target.get("operation", "replace_symbol"),
            target_file=request.target.get("file_path", ""),
            target_symbol=request.target.get("qualname", ""),
            planner_json="{}",
            planner_result_json="{}",
            request=request_value,
            module_outline="[]",
            module_outline_block="",
            target_function_block=target_block,
            full_file_source="",
            generated_test_file=generated_test_file,
            example_test_source=example_value,
            example_test_block=example_block,
        )

    prompt = _render(
        request_value=compact_request_text,
        target_function_value=target_source,
        example_value=example_text,
    )
    before_trim = len(prompt)

    if len(prompt) > available_user_chars:
        example_text, _ = _truncate_text(example_text, 400)
        prompt = _render(
            request_value=compact_request_text,
            target_function_value=target_source,
            example_value=example_text,
        )

    if len(prompt) > available_user_chars:
        target_source, _ = _truncate_text(target_source, 900)
        prompt = _render(
            request_value=compact_request_text,
            target_function_value=target_source,
            example_value=example_text,
        )

    if len(prompt) > available_user_chars:
        target_source, _ = _truncate_text(target_source, 650)
        example_text, _ = _truncate_text(example_text, 220)
        compact_request_text, _ = _truncate_text(compact_request_text, 320)
        prompt = _render(
            request_value=compact_request_text,
            target_function_value=target_source,
            example_value=example_text,
        )

    metrics = {
        "test_prompt_chars_before_trim": before_trim,
        "test_prompt_chars_after_trim": len(prompt),
        "test_target_chars": len(target_source),
        "test_example_chars": len(example_text),
        "test_request_chars": len(compact_request_text),
        "test_target_source_origin": target_source_origin,
    }
    return prompt, metrics
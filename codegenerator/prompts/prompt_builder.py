from __future__ import annotations

import json
import re
from typing import Any
import logging

from codegenerator.config import RuntimeConfig
from codegenerator.models.requests import GenerationRequest, RepairRequest

logger = logging.getLogger(__name__)

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


def _render_related_tests(
    project_context: dict[str, Any],
    max_items: int,
    per_item_chars: int,
) -> tuple[str, dict[str, Any]]:
    tests = list(project_context.get("related_tests") or [])[:max_items]
    blocks: list[str] = []
    total_chars = 0
    qualnames: list[str] = []

    for item in tests:
        raw_source = str(item.get("source", "") or "")
        if not raw_source:
            continue
        source = raw_source
        if per_item_chars > 0 and len(source) > per_item_chars:
            source, _ = _truncate_text(source, per_item_chars)
        qualname = str(item.get("qualname", "") or item.get("name", "") or "")
        file_path = str(item.get("file_path", "") or "")
        kind = str(item.get("kind", "") or "")
        header = f"Qualname: {qualname}\nFile: {file_path}\nKind: {kind}".strip()
        blocks.append(f"{header}\nCode:\n{source}")
        qualnames.append(qualname)
        total_chars += len(source)

    rendered = "\n\n---\n\n".join(blocks) if blocks else "none"
    metrics = {
        "related_tests_count": len(blocks),
        "related_test_chars": total_chars,
        "related_test_qualnames": qualnames,
    }
    return rendered, metrics


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
        content = raw_content
        if per_item_chars > 0 and len(content) > per_item_chars:
            content, _ = _truncate_text(content, per_item_chars)
        title = str(item.get("title", ""))
        usage_mode = str(item.get("usage_mode", ""))
        block = f"Title: {title}\nUsage mode: {usage_mode}\nCode:\n{content}"
        blocks.append(block)
        titles.append(title)
        content_modes.append(str(item.get("content_mode", "")))
        total_chars += len(content)

    rendered = "\n\n---\n\n".join(blocks) if blocks else "none"
    metrics = {
        "reference_count": len(blocks),
        "reference_chars": total_chars,
        "reference_titles": titles,
        "reference_content_modes": content_modes,
    }
    return rendered, metrics


def _build_coder_prompt_metrics(
    prompt: str,
    target_text: str,
    module_outline_text: str,
    full_file_text: str,
    reference_text: str,
    related_tests_text: str,
    before_trim: int,
    after_trim: int,
    trim_steps: list[str] | None = None,
) -> dict[str, Any]:
    normalized_module_outline = _normalize_optional_value(module_outline_text)
    normalized_full_file = _normalize_optional_value(full_file_text)
    normalized_reference = _normalize_optional_value(reference_text)
    normalized_related_tests = _normalize_optional_value(related_tests_text)

    return {
        "coder_prompt_chars_before_trim": before_trim,
        "coder_prompt_chars_after_trim": after_trim,
        "coder_target_chars": len(target_text),
        "coder_module_outline_chars": len(normalized_module_outline),
        "coder_full_file_chars": len(normalized_full_file),
        "coder_reference_chars": len(normalized_reference),
        "coder_related_test_chars": len(normalized_related_tests),
        "coder_trim_steps": list(trim_steps or []),
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
        planner_constraints = [str(item) for item in (planner_result.get("constraints") or []) if item]
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


def build_test_planner_user_prompt(
    template_text: str,
    request: GenerationRequest,
    *,
    generated_code_artifact: dict[str, Any] | None = None,
    available_user_chars: int | None = None,
    default_constraints: list[str] | None = None,
    planner_result: dict[str, Any] | None = None,
    runtime_config: RuntimeConfig | None = None,
) -> tuple[str, dict[str, Any]]:
    pc = request.project_context or {}
    target_symbol = pc.get("target_symbol") or {}
    artifact_payload = _normalize_generated_code_artifact(generated_code_artifact)
    default_constraints = [str(item) for item in (default_constraints or []) if item]

    logger.info(
        "build_test_planner_user_prompt artifact_type=%s normalized_keys=%s available_user_chars_type=%s default_constraints_count=%s",
        type(generated_code_artifact).__name__,
        sorted(artifact_payload.keys()),
        type(available_user_chars).__name__,
        len(default_constraints),
    )

    effective_target_symbol, anchor_symbol = _resolve_test_target_symbol(
        request,
        generated_code_artifact=generated_code_artifact,
    )

    if artifact_payload.get("code"):
        target_source = str(artifact_payload.get("code") or "").strip()
        target_source_origin = "generated_code_artifact"
    else:
        target_source = str(target_symbol.get("source") or "").strip()
        target_source_origin = "project_context.target_symbol"

    compact_request_text = _compact_change_request_for_codegen(
        request.change_request,
        planner_result=planner_result,
    )
    if default_constraints:
        compact_request_text = (
            compact_request_text
            + "\nDefault constraints:\n"
            + "\n".join(f"- {item}" for item in default_constraints[:8])
        ).strip()

    full_file_source = str(pc.get("full_file_source", "") or "").strip()
    planner_related_tests_max_items = (
        runtime_config.prompt_assembly.test_planner_related_tests_max_items
        if runtime_config
        else 1
    )
    planner_related_tests_per_item_chars = (
        runtime_config.prompt_assembly.test_planner_related_tests_per_item_chars
        if runtime_config
        else 450
    )
    related_tests_text, related_test_metrics = _render_related_tests(
        pc,
        max_items=planner_related_tests_max_items,
        per_item_chars=planner_related_tests_per_item_chars,
    )
    if related_tests_text == "none":
        related_tests_text = ""

    reference_context_block, reference_metrics = _build_test_reference_context_block(
        request.reference_context or {},
        runtime_config=runtime_config,
    )

    import_context_text = _extract_import_context(full_file_source)
    inferred_symbols = _infer_project_symbols(target_source)
    inferred_symbols_limit = (
        runtime_config.prompt_assembly.test_planner_inferred_symbols_count
        if runtime_config
        else 20
    )
    inferred_symbols_text = "\n".join(f"- {name}" for name in inferred_symbols[:inferred_symbols_limit])

    if isinstance(available_user_chars, int) and available_user_chars > 0 and runtime_config:
        if len(full_file_source) > runtime_config.prompt_assembly.test_planner_full_file_chars:
            full_file_source, _ = _truncate_text(
                full_file_source,
                runtime_config.prompt_assembly.test_planner_full_file_chars,
            )
        if len(related_tests_text) > runtime_config.prompt_assembly.test_planner_related_tests_chars:
            related_tests_text, _ = _truncate_text(
                related_tests_text,
                runtime_config.prompt_assembly.test_planner_related_tests_chars,
            )
        if len(import_context_text) > runtime_config.prompt_assembly.test_planner_import_context_chars:
            import_context_text, _ = _truncate_text(
                import_context_text,
                runtime_config.prompt_assembly.test_planner_import_context_chars,
            )
        if len(inferred_symbols_text) > runtime_config.prompt_assembly.test_planner_inferred_symbols_chars:
            inferred_symbols_text, _ = _truncate_text(
                inferred_symbols_text,
                runtime_config.prompt_assembly.test_planner_inferred_symbols_chars,
            )

    values = {
        "request": compact_request_text,
        "target_file": request.target.get("file_path", ""),
        "target_symbol": effective_target_symbol,
        "operation": request.target.get("operation", "replace_symbol"),
        "target_source": target_source or "none",
        "full_file_source": full_file_source or "none",
        "related_tests_block": _render_optional_block("Связанные тесты проекта", related_tests_text),
        "import_context_block": _render_optional_block("Импорты из целевого файла", import_context_text),
        "inferred_symbols_block": _render_optional_block("Символы проекта из target-кода", inferred_symbols_text),
        "source_priority_block": "",
        "reference_context_block": reference_context_block,
        "anchor_symbol": anchor_symbol or "null",
    }

    logger.info(
        "build_test_planner_user_prompt template_vars=%s",
        sorted(values.keys()),
    )

    prompt = template_text.format(**values)
    if "{reference_context_block}" not in template_text and values.get("reference_context_block"):
        prompt += values["reference_context_block"]
    if isinstance(available_user_chars, int) and available_user_chars > 0 and len(prompt) > available_user_chars and values.get("reference_context_block"):
        values["reference_context_block"] = ""
        prompt = template_text.format(**values)

    metrics = {
        "test_planner_target_source_origin": target_source_origin,
        "test_planner_effective_target_symbol": effective_target_symbol,
        "test_planner_anchor_symbol": anchor_symbol,
        "test_planner_target_chars": len(target_source),
        "test_planner_full_file_chars": len(full_file_source),
        "test_planner_related_test_chars": int(related_test_metrics.get("related_test_chars", 0) or 0),
        "test_planner_related_tests_count": int(related_test_metrics.get("related_tests_count", 0) or 0),
        "test_planner_import_context_chars": len(import_context_text),
        "test_planner_inferred_symbols_chars": len(inferred_symbols_text),
        "test_planner_request_chars": len(compact_request_text),
        "test_planner_prompt_chars": len(prompt),
        "test_planner_default_constraints_count": len(default_constraints),
        "test_planner_reference_count": int(reference_metrics.get("reference_count", 0) or 0),
        "test_planner_reference_chars": int(reference_metrics.get("reference_chars", 0) or 0),
        "test_planner_has_reference_context": bool(values.get("reference_context_block")),
    }
    return prompt, metrics

def build_planner_user_prompt(
    template_text: str,
    request: GenerationRequest,
    *,
    available_user_chars: int | None = None,
    default_constraints: list[str] | None = None,
) -> tuple[str, dict[str, Any]]:
    pc = request.project_context or {}
    target_symbol = pc.get("target_symbol") or pc.get("target_function") or {}
    default_constraints = [str(item) for item in (default_constraints or []) if item]

    compact_request_text = _compact_change_request_for_codegen(
        request.change_request,
        planner_result=None,
    )
    if default_constraints:
        compact_request_text = (
            compact_request_text
            + "\nDefault constraints:\n"
            + "\n".join(f"- {item}" for item in default_constraints[:8])
        ).strip()

    module_outline_text = _render_module_outline(pc.get("module_outline", []))
    target_source = _render_target_symbol(target_symbol)
    full_file_source = str(pc.get("full_file_source", "") or "").strip()

    related_tests_text, related_test_metrics = _render_related_tests(
        pc,
        max_items=1,
        per_item_chars=450,
    )
    if related_tests_text == "none":
        related_tests_text = ""

    reference_text, reference_metrics = _render_reference_artifacts(
        request.reference_context or {},
        max_items=1,
        per_item_chars=700,
    )
    if reference_text == "none":
        reference_text = ""

    logger.info(
        "build_planner_user_prompt available_user_chars_type=%s default_constraints_count=%s",
        type(available_user_chars).__name__,
        len(default_constraints),
    )

    if isinstance(available_user_chars, int) and available_user_chars > 0:
        if len(module_outline_text) > 700:
            module_outline_text, _ = _truncate_text(module_outline_text, 700)
        if len(target_source) > 1200:
            target_source, _ = _truncate_text(target_source, 1200)
        if len(full_file_source) > 1200:
            full_file_source, _ = _truncate_text(full_file_source, 1200)
        if len(related_tests_text) > 450:
            related_tests_text, _ = _truncate_text(related_tests_text, 450)
        if len(reference_text) > 700:
            reference_text, _ = _truncate_text(reference_text, 700)

    values = {
        "request": compact_request_text,
        "target_file": request.target.get("file_path", ""),
        "target_symbol": request.target.get("qualname", ""),
        "operation": request.target.get("operation", "replace_symbol"),
        "insert_after": request.target.get("insert_after") or request.target.get("qualname", "") or "null",
        "reference_symbol": "null",
        "module_outline_block": _render_optional_block("Структура модуля", module_outline_text),
        "target_function_block": _render_optional_block("Целевой symbol / anchor", target_source),
        "full_file_source_block": _render_optional_block("Полный исходный текст файла", full_file_source),
        "related_tests_block": _render_optional_block("Связанные тесты проекта", related_tests_text),
        "reference_function_block": _render_optional_block("Reference artifacts", reference_text),
    }

    logger.info(
        "build_planner_user_prompt template_vars=%s",
        sorted(values.keys()),
    )

    prompt = template_text.format(**values)

    prompt = template_text.format(**values)
    metrics = {
        "planner_prompt_chars": len(prompt),
        "planner_request_chars": len(compact_request_text),
        "planner_module_outline_chars": len(module_outline_text),
        "planner_target_chars": len(target_source),
        "planner_full_file_chars": len(full_file_source),
        "planner_related_tests_count": int(related_test_metrics.get("related_tests_count", 0) or 0),
        "planner_related_test_chars": int(related_test_metrics.get("related_test_chars", 0) or 0),
        "planner_reference_count": int(reference_metrics.get("reference_count", 0) or 0),
        "planner_reference_chars": int(reference_metrics.get("reference_chars", 0) or 0),
        "planner_default_constraints_count": len(default_constraints),
    }
    return prompt, metrics

def build_coder_user_prompt(
    template_text: str,
    request: GenerationRequest,
    planner_result: dict[str, Any],
    runtime_config: RuntimeConfig,
    available_user_chars: int | None = None,
) -> tuple[str, dict[str, Any]]:
    pc = request.project_context or {}
    request_mode = str(getattr(request, "mode", "generate") or "generate")
    requested_operation = str(
        request.target.get("operation", "replace_symbol") or "replace_symbol"
    ).strip()

    module_outline_text = _normalize_optional_value(
        _render_module_outline(pc.get("module_outline", []))
    )
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
    full_file_text = _normalize_optional_value(full_file_text)

    reference_text, ref_metrics = _render_reference_artifacts(
        request.reference_context or {},
        runtime_config.coder_max_reference_artifacts,
        runtime_config.coder_max_reference_chars,
    )
    reference_text = _normalize_optional_value(reference_text)

    related_tests_text, related_test_metrics = _render_related_tests(
        pc,
        max_items=1,
        per_item_chars=450,
    )
    related_tests_text = _normalize_optional_value(related_tests_text)

    compact_request_text = _compact_change_request_for_codegen(
        request.change_request,
        planner_result,
    )

    target_limit = int(runtime_config.coder_prompt_target_chars or 0)
    hard_limit = int(runtime_config.coder_prompt_hard_limit or 0)
    runtime_limit = int(available_user_chars or 0) if available_user_chars else 0

    # Это не жесткий лимит, а рабочая цель.
    # Даем небольшой люфт, потому что planner и coder могут слегка выходить за target.
    soft_limit = target_limit + 250 if target_limit > 0 else 0

    # Реальный предел, после которого уже надо агрессивно ужиматься.
    effective_limit = runtime_limit or hard_limit or soft_limit or 0

    trim_steps: list[str] = []

    def _record(step: str) -> None:
        trim_steps.append(step)

    def _render(
        module_outline_value: str,
        target_value: str,
        full_file_value: str,
        reference_value: str,
        related_tests_value: str,
        request_value: str,
    ) -> str:
        return template_text.format(
            operation=request.target.get("operation", "replace_symbol"),
            target_file=request.target.get("file_path", ""),
            target_symbol=request.target.get("qualname", ""),
            insert_after=request.target.get("insert_after")
            or request.target.get("qualname", "")
            or "null",
            reference_symbol="null",
            planner_json=_pretty(planner_result),
            request=request_value,
            module_outline_block=_render_optional_block(
                "Структура модуля",
                _normalize_optional_value(module_outline_value),
            ),
            target_function_block=_render_optional_block(
                "Целевой symbol / anchor",
                target_value,
            ),
            reference_function_block=_render_optional_block(
                "Функция-образец",
                _normalize_optional_value(reference_value),
            ),
            full_file_source_block=_render_optional_block(
                "Полный исходный текст файла",
                _normalize_optional_value(full_file_value),
            ),
            related_tests_block=_render_optional_block(
                "Related tests",
                _normalize_optional_value(related_tests_value),
            ),
        )

    # Обязательные части
    current_module_outline = module_outline_text
    current_target = target_text
    current_request = compact_request_text

    # Опциональные части будем подключать по приоритету
    current_full_file = ""
    current_related_tests = ""
    current_reference = ""

    # Для insert_after_symbol reference обычно наименее надежен,
    # поэтому даем ему самый низкий приоритет.
    # Для остальных операций тоже держим reference ниже related_tests.
    if requested_operation == "insert_after_symbol":
        optional_blocks: list[tuple[str, str]] = [
            ("module_outline", current_module_outline),
            ("related_tests", related_tests_text),
            ("full_file", full_file_text),
            ("reference", reference_text),
        ]
    else:
        optional_blocks = [
            ("module_outline", current_module_outline),
            ("full_file", full_file_text),
            ("related_tests", related_tests_text),
            ("reference", reference_text),
        ]

    # Сначала базовый prompt без опциональных тяжелых блоков
    prompt = _render(
        current_module_outline,
        current_target,
        current_full_file,
        current_reference,
        current_related_tests,
        current_request,
    )
    before_trim = len(prompt)

    # Если уже слишком длинно, сначала слегка ужимаем request/target/outline
    if soft_limit and len(prompt) > soft_limit:
        current_request, _ = _truncate_text(current_request, 260)
        _record("truncated request to 260 in base prompt")
        prompt = _render(
            current_module_outline,
            current_target,
            current_full_file,
            current_reference,
            current_related_tests,
            current_request,
        )

    if soft_limit and len(prompt) > soft_limit and current_target:
        current_target, _ = _truncate_text(current_target, 500)
        _record("truncated target to 500 in base prompt")
        prompt = _render(
            current_module_outline,
            current_target,
            current_full_file,
            current_reference,
            current_related_tests,
            current_request,
        )

    if soft_limit and len(prompt) > soft_limit and current_module_outline:
        current_module_outline, _ = _truncate_text(current_module_outline, 220)
        _record("truncated module_outline to 220 in base prompt")
        prompt = _render(
            current_module_outline,
            current_target,
            current_full_file,
            current_reference,
            current_related_tests,
            current_request,
        )

    # Теперь последовательно пытаемся добавить блоки по приоритету.
    for block_name, block_value in optional_blocks:
        block_text = _normalize_optional_value(block_value)
        if not block_text:
            continue

        prev_full_file = current_full_file
        prev_related_tests = current_related_tests
        prev_reference = current_reference
        prev_module_outline = current_module_outline

        if block_name == "full_file":
            current_full_file = block_text
        elif block_name == "related_tests":
            current_related_tests = block_text
        elif block_name == "reference":
            current_reference = block_text
        elif block_name == "module_outline":
            current_module_outline = block_text

        candidate_prompt = _render(
            current_module_outline,
            current_target,
            current_full_file,
            current_reference,
            current_related_tests,
            current_request,
        )

        # Если вылезли слишком далеко за рабочую цель — откатываем этот блок.
        if soft_limit and len(candidate_prompt) > soft_limit:
            current_full_file = prev_full_file
            current_related_tests = prev_related_tests
            current_reference = prev_reference
            current_module_outline = prev_module_outline
            _record(f"skipped {block_name} due to soft size target")
            continue

        prompt = candidate_prompt
        _record(f"kept {block_name}")

    # Финальная простая стадия дожатия.
    # Не делаем сложный каскад, а идем по понятному порядку.
    if effective_limit and len(prompt) > effective_limit and current_reference:
        current_reference = ""
        _record("removed reference on effective limit")
        prompt = _render(
            current_module_outline,
            current_target,
            current_full_file,
            current_reference,
            current_related_tests,
            current_request,
        )

    if effective_limit and len(prompt) > effective_limit and current_full_file:
        current_full_file, _ = _truncate_text(current_full_file, 220)
        _record("truncated full_file to 220 on effective limit")
        prompt = _render(
            current_module_outline,
            current_target,
            current_full_file,
            current_reference,
            current_related_tests,
            current_request,
        )

    if effective_limit and len(prompt) > effective_limit and current_related_tests:
        current_related_tests, _ = _truncate_text(current_related_tests, 180)
        _record("truncated related_tests to 180 on effective limit")
        prompt = _render(
            current_module_outline,
            current_target,
            current_full_file,
            current_reference,
            current_related_tests,
            current_request,
        )

    if effective_limit and len(prompt) > effective_limit and current_full_file:
        current_full_file = ""
        _record("removed full_file on hard overflow")
        prompt = _render(
            current_module_outline,
            current_target,
            current_full_file,
            current_reference,
            current_related_tests,
            current_request,
        )

    if effective_limit and len(prompt) > effective_limit and current_related_tests:
        current_related_tests = ""
        _record("removed related_tests on hard overflow")
        prompt = _render(
            current_module_outline,
            current_target,
            current_full_file,
            current_reference,
            current_related_tests,
            current_request,
        )

    if effective_limit and len(prompt) > effective_limit and current_module_outline:
        current_module_outline, _ = _truncate_text(current_module_outline, 120)
        _record("truncated module_outline to 120 on hard overflow")
        prompt = _render(
            current_module_outline,
            current_target,
            current_full_file,
            current_reference,
            current_related_tests,
            current_request,
        )

    if effective_limit and len(prompt) > effective_limit and current_request:
        current_request, _ = _truncate_text(current_request, 160)
        _record("truncated request to 160 on hard overflow")
        prompt = _render(
            current_module_outline,
            current_target,
            current_full_file,
            current_reference,
            current_related_tests,
            current_request,
        )

    if effective_limit and len(prompt) > effective_limit and current_target:
        current_target, _ = _truncate_text(current_target, 160)
        _record("truncated target to 160 on hard overflow")
        prompt = _render(
            current_module_outline,
            current_target,
            current_full_file,
            current_reference,
            current_related_tests,
            current_request,
        )

    metrics = _build_coder_prompt_metrics(
        prompt,
        current_target,
        current_module_outline,
        current_full_file,
        current_reference,
        current_related_tests,
        before_trim,
        len(prompt),
        trim_steps,
    )
    metrics.update(ref_metrics)
    metrics.update(related_test_metrics)

    logger.info(
        "coder prompt priority assembly request_id=%s operation=%s soft_limit=%s effective_limit=%s final_chars=%s trim_steps=%s",
        request.request_id,
        requested_operation,
        soft_limit,
        effective_limit,
        len(prompt),
        trim_steps,
    )

    return prompt, metrics


def _build_reference_context_block(
    reference_context: dict[str, Any],
    runtime_config: RuntimeConfig | None,
) -> str:
    max_chars = runtime_config.repair_max_reference_chars if runtime_config else 220
    artifacts = list(reference_context.get("reference_artifacts") or [])[:1]

    compact_items: list[dict[str, Any]] = []
    for item in artifacts:
        raw_content = str(item.get("content", "") or "")
        truncated_content, _ = _truncate_text(raw_content, max_chars)
        compact_items.append(
            {
                "title": item.get("title", ""),
                "usage_mode": item.get("usage_mode", ""),
                "content_mode": item.get("content_mode", ""),
                "content": truncated_content,
            }
        )

    if not compact_items:
        return ""

    return _render_optional_block(
        "Справочный контекст",
        _pretty({"reference_artifacts": compact_items}),
    )


def _build_repair_previous_code_block(
    previous_artifact: dict[str, Any],
) -> str:
    code = str(previous_artifact.get("code", "") or "").strip()
    return _render_optional_block("Код, который нужно исправить", code)

def _build_repair_syntax_error_block(
    error_context: dict[str, Any],
) -> str:
    verification_summary = (error_context or {}).get("verification_summary") or {}
    failed_blocks = verification_summary.get("failed_blocks") or []

    for block in failed_blocks:
        issues = block.get("issues") or []
        details = block.get("details") or {}

        for issue in issues:
            code = str(issue.get("code", "") or "")
            message = str(issue.get("message", "") or "")
            if code == "SyntaxError" or "syntax" in code.lower():
                return _render_optional_block(
                    "Локальная синтаксическая диагностика",
                    _pretty(
                        {
                            "code": code,
                            "message": message,
                            "details": details,
                        }
                    ),
                )

        error_type = str(details.get("error_type", "") or "")
        message = str(details.get("message", "") or "")
        if error_type == "SyntaxError" or "syntax" in error_type.lower():
            return _render_optional_block(
                "Локальная синтаксическая диагностика",
                _pretty(
                    {
                        "code": error_type or "SyntaxError",
                        "message": message,
                        "details": details,
                    }
                ),
            )

    return ""

def _render_optional_block(title: str, value: str) -> str:
    text = str(value or "").strip()
    if not text or text in {"none", "[]", "null"}:
        return ""
    return f"\n\n{title}:\n{text}"

def _normalize_optional_value(value: str | None) -> str:
    text = str(value or "").strip()
    if not text or text in {"none", "[]", "null"}:
        return ""
    return text


def build_repair_user_prompt(
    template_text: str,
    request: RepairRequest,
    runtime_config: RuntimeConfig | None = None,
) -> str:
    project_context = request.project_context or {}
    target_symbol = project_context.get("target_symbol") or {}
    previous_artifact = request.previous_artifact or {}
    change_request = request.change_request or {}

    requested_operation = previous_artifact.get("operation") or "replace_symbol"
    hard_limit = int(runtime_config.repair_prompt_hard_limit or 0) if runtime_config else 0

    module_outline_text = _normalize_optional_value(
        _render_module_outline(project_context.get("module_outline", []))
    )
    if module_outline_text:
        module_outline_text, _ = _truncate_text(module_outline_text, 220)
        module_outline_text = _normalize_optional_value(module_outline_text)

    full_file_source = str(project_context.get("full_file_source", "") or "")
    if runtime_config and runtime_config.coder_max_full_file_chars <= 0:
        full_file_source = ""
    elif full_file_source:
        full_file_source, _ = _truncate_text(full_file_source, 350)
    full_file_source = _normalize_optional_value(full_file_source)

    target_rendered = _render_target_symbol(target_symbol)
    if target_rendered:
        target_rendered, _ = _truncate_text(target_rendered, 420)
    target_rendered = _normalize_optional_value(target_rendered)

    previous_code = str(previous_artifact.get("code", "") or "")
    if previous_code:
        previous_code, _ = _truncate_text(previous_code, 700)
    previous_code = _normalize_optional_value(previous_code)

    reference_context_block = _build_reference_context_block(
        request.reference_context or {},
        runtime_config,
    )
    syntax_error_block = _build_repair_syntax_error_block(
        request.error_context or {},
    )
# ***********************
    has_local_syntax_error = bool(syntax_error_block)
    has_previous_code = bool(previous_code)
# ***********************
    if has_local_syntax_error and has_previous_code:
        module_outline_text = ""

    values = {
        "requested_operation": requested_operation,
        "target_file": previous_artifact.get("target_file", ""),
        "target_symbol": previous_artifact.get(
            "target_qualname",
            previous_artifact.get("target_symbol", ""),
        ),
        "insert_after": previous_artifact.get("insert_after") or "null",
        "request": _compact_change_request_for_codegen(change_request, None) or "repair request",
        "syntax_error_block": syntax_error_block,
        "previous_code_block": _render_optional_block(
            "Код, который нужно исправить",
            previous_code,
        ),
        "target_function_block": _render_optional_block(
            "Исходный target symbol",
            target_rendered,
        ),
        "module_outline_block": _render_optional_block(
            "Структура модуля",
            module_outline_text,
        ),
        "full_file_source_block": _render_optional_block(
            "Полный исходный текст файла",
            full_file_source,
        ),
        "reference_context_block": reference_context_block,
    }

    prompt = template_text.format(**values)
    trim_steps: list[str] = []

    def _rerender() -> str:
        return template_text.format(**values)

    if hard_limit and len(prompt) > hard_limit and values["reference_context_block"]:
        values["reference_context_block"] = ""
        trim_steps.append("removed reference_context_block")
        prompt = _rerender()

    if hard_limit and len(prompt) > hard_limit and values["module_outline_block"]:
        values["module_outline_block"] = ""
        trim_steps.append("removed module_outline_block")
        prompt = _rerender()

    if hard_limit and len(prompt) > hard_limit and values["full_file_source_block"]:
        values["full_file_source_block"] = ""
        trim_steps.append("removed full_file_source_block")
        prompt = _rerender()

    if hard_limit and len(prompt) > hard_limit and previous_code:
        compact_previous_code, _ = _truncate_text(previous_code, 450)
        values["previous_code_block"] = _render_optional_block(
            "Код, который нужно исправить",
            compact_previous_code,
        )
        trim_steps.append("truncated previous_code_block to 450")
        prompt = _rerender()

    logger.info(
        "repair prompt assembly request_id=%s hard_limit=%s final_chars=%s trim_steps=%s "
        "has_previous_code=%s has_target=%s has_module_outline=%s has_full_file=%s has_reference=%s",
        request.request_id,
        hard_limit,
        len(prompt),
        trim_steps,
        bool(values["previous_code_block"]),
        bool(values["target_function_block"]),
        bool(values["module_outline_block"]),
        bool(values["full_file_source_block"]),
        bool(values["reference_context_block"]),
    )

    return prompt


def _extract_import_context(full_file_source: str) -> str:
    if not full_file_source.strip():
        return ""
    imports: list[str] = []
    for line in full_file_source.splitlines():
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            imports.append(stripped)
    return "\n".join(imports)


def _infer_project_symbols(target_source: str) -> list[str]:
    candidates = re.findall(r"\b([A-Z][A-Za-z0-9_]*)\b", target_source)
    excluded = {"True", "False", "None", "JSON", "Python"}
    seen: list[str] = []
    for item in candidates:
        if item in excluded or item in seen:
            continue
        seen.append(item)
    return seen

def _extract_declared_symbol_name(code: str) -> str | None:
    source = (code or "").strip()
    if not source:
        return None

    class_match = re.search(
        r"(?m)^(?:@[^\n]+\n)*class\s+([A-Za-z_][A-Za-z0-9_]*)\b",
        source,
    )
    if class_match:
        return class_match.group(1)

    func_match = re.search(
        r"(?m)^(?:@[^\n]+\n)*def\s+([A-Za-z_][A-Za-z0-9_]*)\b",
        source,
    )
    if func_match:
        return func_match.group(1)

    return None

def _normalize_generated_code_artifact(
    generated_code_artifact: Any,
) -> dict[str, Any]:
    if isinstance(generated_code_artifact, dict):
        return generated_code_artifact

    if isinstance(generated_code_artifact, list):
        for item in generated_code_artifact:
            if isinstance(item, dict):
                return item
        return {}

    return {}

def _resolve_test_target_symbol(
    request: GenerationRequest,
    generated_code_artifact: Any = None,
) -> tuple[str, str | None]:
    requested_operation = (
        str(request.target.get("operation", "") or "").strip()
        or "replace_symbol"
    )

    anchor_symbol = str(request.target.get("qualname", "") or "").strip()

    if requested_operation != "insert_after_symbol":
        return anchor_symbol, None

    artifact_payload = _normalize_generated_code_artifact(generated_code_artifact)
    generated_code = str(artifact_payload.get("code", "") or "")

    generated_symbol_name = _extract_declared_symbol_name(generated_code)
    if not generated_symbol_name:
        return anchor_symbol, anchor_symbol or None

    target_file = str(request.target.get("file_path", "") or "").strip()
    module_name = target_file[:-3].replace("/", ".") if target_file.endswith(".py") else ""

    effective_symbol = (
        f"{module_name}.{generated_symbol_name}"
        if module_name
        else generated_symbol_name
    )
    return effective_symbol, anchor_symbol or None

def _build_test_reference_context_block(
    reference_context: dict[str, Any],
    runtime_config: RuntimeConfig | None,
) -> tuple[str, dict[str, Any]]:
    max_chars = int(runtime_config.test_prompt_reference_chars or 0) if runtime_config else 420
    max_items = runtime_config.prompt_assembly.test_reference_max_items if runtime_config else 1
    if max_chars <= 0 or max_items <= 0:
        return "", {"reference_count": 0, "reference_chars": 0}
    reference_text, metrics = _render_reference_artifacts(
        reference_context or {},
        max_items=max_items,
        per_item_chars=max_chars,
    )
    reference_text = _normalize_optional_value(reference_text)
    if not reference_text:
        return "", metrics
    return _render_optional_block("Справочные примеры для теста", reference_text), metrics


def _build_test_prompt_values(
    *,
    request: GenerationRequest,
    generated_test_file: str,
    compact_request_text: str,
    target_source: str,
    example_text: str,
    related_tests_text: str,
    import_context_text: str,
    inferred_symbols_text: str,
    full_file_source_text: str,
    effective_target_symbol: str,
    effective_target_kind: str,
    effective_target_name: str,
    anchor_symbol: str | None,
    test_plan_text: str,
    reference_context_block: str = "",
) -> dict[str, str]:
    target_block = _render_optional_block("Сгенерированный target-код", target_source)
    example_block = _render_optional_block("Пример теста", example_text)
    related_tests_block = _render_optional_block("Связанные тесты проекта", related_tests_text)
    import_context_block = _render_optional_block("Импорты из целевого файла", import_context_text)
    inferred_symbols_block = _render_optional_block(
        "Символы проекта из target-кода",
        inferred_symbols_text,
    )
    full_file_source_block = _render_optional_block(
        "Полный исходный текст целевого файла",
        full_file_source_text,
    )
    test_plan_block = _render_optional_block(
        "План теста",
        test_plan_text,
    )
    return {
        "operation": request.target.get("operation", "replace_symbol"),
        "target_file": request.target.get("file_path", ""),
        "target_symbol": effective_target_symbol,
        "effective_target_kind": effective_target_kind,
        "effective_target_name": effective_target_name,
        "insert_after": anchor_symbol or request.target.get("insert_after") or "null",
        "planner_json": "{}",
        "planner_result_json": "{}",
        "request": compact_request_text,
        "module_outline": "[]",
        "module_outline_block": "",
        "source_priority_block": "",
        "target_function_block": target_block,
        "full_file_source": full_file_source_text,
        "full_file_source_block": full_file_source_block,
        "generated_test_file": generated_test_file,
        "example_test_source": example_text,
        "example_test_block": example_block,
        "related_tests_block": related_tests_block,
        "import_context_block": import_context_block,
        "inferred_symbols_block": inferred_symbols_block,
        "test_plan_block": test_plan_block,
        "reference_context_block": reference_context_block,
    }

def _log_test_prompt_state(
    stage: str,
    *,
    requested_operation: str,
    available_user_chars: int,
    prompt_len: int,
    target_source: str,
    example_text: str,
    related_tests_text: str,
    import_context_text: str,
    inferred_symbols_text: str,
    compact_request_text: str,
    effective_target_symbol: str,
    anchor_symbol: str | None,
    reference_context_block: str = "",
) -> None:
    logger.info(
        "Test prompt state stage=%s operation=%s prompt_chars=%s available_user_chars=%s "
        "target_chars=%s request_chars=%s example_chars=%s related_tests_chars=%s "
        "has_related_tests=%s import_context_chars=%s inferred_symbols_chars=%s "
        "reference_chars=%s has_reference=%s effective_target_symbol=%s anchor_symbol=%s",
        stage,
        requested_operation,
        prompt_len,
        available_user_chars,
        len(target_source or ""),
        len(compact_request_text or ""),
        len(example_text or ""),
        len(related_tests_text or ""),
        bool(str(related_tests_text or "").strip()),
        len(import_context_text or ""),
        len(inferred_symbols_text or ""),
        len(reference_context_block or ""),
        bool(str(reference_context_block or "").strip()),
        effective_target_symbol,
        anchor_symbol,
    )

def build_test_generator_user_prompt(
    template_text: str,
    request: GenerationRequest,
    generated_test_file: str,
    example_test_source: str,
    runtime_config: RuntimeConfig,
    available_user_chars: int,
    generated_code_artifact: Any = None,
    test_plan: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    pc = request.project_context or {}
    effective_test_plan = test_plan or request.test_plan or {}
    test_plan_text = _pretty(effective_test_plan) if effective_test_plan else ""    
    target_symbol = pc.get("target_symbol") or {}
    compact_request_text = _compact_change_request_for_codegen(
        request.change_request,
        planner_result=None,
    )
    effective_target_symbol, anchor_symbol = _resolve_test_target_symbol(
        request,
        generated_code_artifact=generated_code_artifact,
    )
    artifact_payload = _normalize_generated_code_artifact(generated_code_artifact)
    effective_target_kind = "function"
    if artifact_payload.get("code"):
        target_source = str(artifact_payload.get("code", "")).strip()
        target_source_origin = "generated_code_artifact"
    else:
        target_source = str(target_symbol.get("source", "") or "").strip()
        target_source_origin = "project_context.target_symbol"

    stripped_target_source = target_source.strip()
    if stripped_target_source.startswith("class ") or "\nclass " in stripped_target_source:
        effective_target_kind = "class"

    effective_target_name = (
        effective_target_symbol.rsplit(".", 1)[-1]
        if effective_target_symbol
        else ""
    )

    full_file_source_text = str(pc.get("full_file_source", "") or "").strip()

    related_tests_text, related_test_metrics = _render_related_tests(
        pc,
        max_items=1,
        per_item_chars=500,
    )

    has_related_tests = bool(str(related_tests_text or "").strip()) and related_tests_text != "none"
    if has_related_tests:
        example_text = ""
    else:
        example_text, _ = _truncate_text(example_test_source or "", 700)

    reference_context_block, reference_metrics = _build_test_reference_context_block(
        request.reference_context or {},
        runtime_config,
    )

    import_context_text = _extract_import_context(full_file_source_text)
    inferred_symbols = _infer_project_symbols(target_source)
    inferred_symbols_text = "\n".join(f"- {name}" for name in inferred_symbols)

    requested_operation = (
        str(request.target.get("operation", "") or "").strip()
        or "replace_symbol"
    )

    trim_steps: list[str] = []

    # Мягкий запас настраивается через config.yaml: лучше сохранить проектный контекст,
    # чем идеально уложиться в лимит, но потерять full_file/related_tests.
    soft_overflow_chars = runtime_config.prompt_assembly.test_soft_overflow_chars

    def _record(step: str) -> None:
        trim_steps.append(step)

    def _clear_related_tests(reason: str) -> None:
        nonlocal related_tests_text, related_test_metrics
        related_tests_text = ""
        related_test_metrics = {
            **related_test_metrics,
            "related_tests_count": 0,
            "related_test_chars": 0,
            "related_test_qualnames": [],
        }
        _record(reason)

    def _truncate_related_tests_once(limit: int, reason: str) -> None:
        nonlocal related_tests_text, related_test_metrics
        if not related_tests_text:
            return
        compact_text, was_truncated = _truncate_text(related_tests_text, limit)
        if was_truncated:
            related_tests_text = compact_text
            related_test_metrics = {
                **related_test_metrics,
                "related_test_chars": len(compact_text),
            }
            _record(reason)

    def _truncate_full_file_once(limit: int, reason: str) -> None:
        nonlocal full_file_source_text
        if not full_file_source_text:
            return
        compact_text, was_truncated = _truncate_text(full_file_source_text, limit)
        if was_truncated:
            full_file_source_text = compact_text
            _record(reason)

    if requested_operation == "insert_after_symbol":
        if example_text:
            limit = runtime_config.prompt_assembly.test_insert_after_example_chars
            example_text, _ = _truncate_text(example_text, limit)
            _record(f"truncated example_text to {limit} for insert_after_symbol")

        if import_context_text:
            limit = runtime_config.prompt_assembly.test_insert_after_import_context_chars
            import_context_text, _ = _truncate_text(import_context_text, limit)
            _record(f"truncated import_context to {limit} for insert_after_symbol")

        if inferred_symbols_text:
            limit = runtime_config.prompt_assembly.test_insert_after_inferred_symbols_chars
            inferred_symbols_text, _ = _truncate_text(inferred_symbols_text, limit)
            _record(f"truncated inferred_symbols to {limit} for insert_after_symbol")

        if compact_request_text:
            limit = runtime_config.prompt_assembly.test_insert_after_request_chars
            compact_request_text, _ = _truncate_text(compact_request_text, limit)
            _record(f"truncated request to {limit} for insert_after_symbol")

    def _render_prompt() -> str:
        values = _build_test_prompt_values(
            request=request,
            generated_test_file=generated_test_file,
            compact_request_text=compact_request_text,
            target_source=target_source,
            example_text=example_text,
            related_tests_text=related_tests_text,
            import_context_text=import_context_text,
            inferred_symbols_text=inferred_symbols_text,
            full_file_source_text=full_file_source_text,
            effective_target_symbol=effective_target_symbol,
            effective_target_kind=effective_target_kind,
            effective_target_name=effective_target_name,
            anchor_symbol=anchor_symbol,
            test_plan_text=test_plan_text,
            reference_context_block=reference_context_block,
        )
        prompt_value = template_text.format(**values)
        if "{reference_context_block}" not in template_text and values.get("reference_context_block"):
            prompt_value += values["reference_context_block"]
        return prompt_value

    def _log(stage: str, prompt_value: str) -> None:
        _log_test_prompt_state(
            stage,
            requested_operation=requested_operation,
            available_user_chars=available_user_chars,
            prompt_len=len(prompt_value),
            target_source=target_source,
            example_text=example_text,
            related_tests_text=related_tests_text,
            import_context_text=import_context_text,
            inferred_symbols_text=inferred_symbols_text,
            compact_request_text=compact_request_text,
            effective_target_symbol=effective_target_symbol,
            anchor_symbol=anchor_symbol,
            reference_context_block=reference_context_block,
        )

    def _fits_with_soft_overflow(prompt_value: str) -> bool:
        if len(prompt_value) <= available_user_chars:
            return True
        if len(prompt_value) <= available_user_chars + soft_overflow_chars:
            return True
        return False

    prompt = _render_prompt()
    before_trim = len(prompt)
    _log("initial", prompt)

    if len(prompt) > available_user_chars and example_text:
        example_text = ""
        _record("removed example_text on size limit")
        prompt = _render_prompt()
        _log("after_remove_example", prompt)

    if len(prompt) > available_user_chars and inferred_symbols_text:
        inferred_symbols_text = ""
        _record("removed inferred_symbols on size limit")
        prompt = _render_prompt()
        _log("after_remove_inferred_symbols", prompt)

    if len(prompt) > available_user_chars and compact_request_text:
        compact_request_text = ""
        _record("removed compact_request_text on size limit")
        prompt = _render_prompt()
        _log("after_remove_request", prompt)

    if len(prompt) > available_user_chars and reference_context_block:
        reference_context_block = ""
        _record("removed reference_context_block on size limit")
        prompt = _render_prompt()
        _log("after_remove_reference_context", prompt)

    # Одна простая попытка ужать related tests, не вводя многоступенчатую схему.
    if len(prompt) > available_user_chars and related_tests_text:
        _truncate_related_tests_once(
            runtime_config.test_prompt_related_tests_truncate_chars,
            f"truncated related_tests once to {runtime_config.test_prompt_related_tests_truncate_chars} on size limit",
        )
        prompt = _render_prompt()
        _log("after_truncate_related_tests_once", prompt)

    # Одна простая попытка ужать full file, а не выбрасывать его сразу.
    if len(prompt) > available_user_chars and full_file_source_text:
        _truncate_full_file_once(
            runtime_config.test_prompt_full_file_truncate_chars,
            f"truncated full_file_source once to {runtime_config.test_prompt_full_file_truncate_chars} on size limit",
        )
        prompt = _render_prompt()
        _log("after_truncate_full_file_once", prompt)

    if len(prompt) > available_user_chars and target_source:
        target_source, _ = _truncate_text(
            target_source,
            runtime_config.test_prompt_target_truncate_chars,
        )
        _record(
            f"truncated target_source to {runtime_config.test_prompt_target_truncate_chars} on size limit"
        )
        prompt = _render_prompt()
        _log("after_truncate_target", prompt)

    if len(prompt) > available_user_chars and import_context_text:
        import_context_text = ""
        _record("removed import_context on size limit")
        prompt = _render_prompt()
        _log("after_remove_import_context", prompt)

# Full file убираем раньше related tests:
# related tests для тестогенерации обычно ценнее, потому что показывают
# реальный паттерн создания и использования project objects.
# import_context тоже стараемся держать дольше, потому что он помогает
# использовать реальные import path и не придумывать отсутствующие модули.
    if not _fits_with_soft_overflow(prompt) and reference_context_block:
        reference_context_block = ""
        _record("removed reference_context_block on hard size overflow")
        prompt = _render_prompt()
        _log("after_remove_reference_context_hard", prompt)

    if not _fits_with_soft_overflow(prompt) and full_file_source_text:
        full_file_source_text = ""
        _record("removed full_file_source context on hard size overflow")
        prompt = _render_prompt()
        _log("after_remove_full_file_context", prompt)

    # Related tests выбрасываем только в самом конце.
    if not _fits_with_soft_overflow(prompt) and related_tests_text:
        _clear_related_tests("removed related_tests on hard size overflow")
        prompt = _render_prompt()
        _log("after_remove_related_tests", prompt)

    if not _fits_with_soft_overflow(prompt) and import_context_text:
        import_context_text = ""
        _record("removed import_context on hard size overflow")
        prompt = _render_prompt()
        _log("after_remove_import_context_hard", prompt)        

    if not full_file_source_text.strip() and not str(related_tests_text or "").strip():
        logger.warning(
            "test prompt degraded: both full_file_source and related_tests were removed; "
            "generation will rely mostly on target code"
        )

    logger.info(
        "test prompt final blocks operation=%s prompt_chars=%s available_user_chars=%s "
        "soft_overflow_chars=%s has_request=%s has_full_file=%s has_example=%s "
        "has_related_tests=%s target_chars=%s request_chars=%s full_file_chars=%s "
        "example_chars=%s related_tests_chars=%s reference_chars=%s has_reference=%s",
        requested_operation,
        len(prompt),
        available_user_chars,
        soft_overflow_chars,
        bool(compact_request_text.strip()),
        bool(full_file_source_text.strip()),
        bool(example_text.strip()),
        bool(str(related_tests_text or "").strip()),
        len(target_source),
        len(compact_request_text),
        len(full_file_source_text),
        len(example_text),
        len(related_tests_text or ""),
        len(reference_context_block or ""),
        bool(str(reference_context_block or "").strip()),
    )

    _log("final", prompt)

    metrics = {
        "test_prompt_chars_before_trim": before_trim,
        "test_prompt_chars_after_trim": len(prompt),
        "test_target_chars": len(target_source),
        "test_example_chars": len(example_text),
        "test_request_chars": len(compact_request_text),
        "test_target_source_origin": target_source_origin,
        "test_related_tests_count": related_test_metrics.get("related_tests_count", 0),
        "test_related_test_chars": related_test_metrics.get("related_test_chars", 0),
        "test_related_test_qualnames": related_test_metrics.get("related_test_qualnames", []),
        "test_import_context_chars": len(import_context_text),
        "test_inferred_project_symbols": inferred_symbols,
        "test_effective_target_symbol": effective_target_symbol,
        "test_anchor_symbol": anchor_symbol,
        "test_effective_target_kind": effective_target_kind,
        "test_effective_target_name": effective_target_name,
        "test_trim_steps": trim_steps,
        "test_reference_count": int(reference_metrics.get("reference_count", 0) or 0),
        "test_reference_chars": int(reference_metrics.get("reference_chars", 0) or 0),
        "test_has_example_block": bool(example_text),
        "test_has_related_tests_block": bool(str(related_tests_text or "").strip()),
        "test_has_import_context_block": bool(import_context_text),
        "test_has_inferred_symbols_block": bool(inferred_symbols_text),
        "test_has_full_file_context": bool(full_file_source_text),
        "test_has_reference_context": bool(reference_context_block),
    }
    return prompt, metrics
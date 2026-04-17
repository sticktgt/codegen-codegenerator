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
        insert_after=target.get("insert_after") or target.get("qualname", "") or "null",
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
    request_mode = str(getattr(request, 'mode', 'generate') or 'generate')
    module_outline_text = _normalize_optional_value(_render_module_outline(pc.get("module_outline", [])))
    target_text = _render_target_symbol(pc.get("target_symbol") or pc.get("target_function") or {})
    full_file_text = str(pc.get("full_file_source", "") or "")

    if runtime_config.coder_max_full_file_chars <= 0:
        full_file_text = ""
    else:
        full_file_text, _ = _truncate_text(full_file_text, runtime_config.coder_max_full_file_chars)
    full_file_text = _normalize_optional_value(full_file_text)

    reference_text, ref_metrics = _render_reference_artifacts(
        request.reference_context or {},
        runtime_config.coder_max_reference_artifacts,
        runtime_config.coder_max_reference_chars,
    )
    reference_text = _normalize_optional_value(reference_text)

    related_tests_text, related_test_metrics = _render_related_tests(pc, max_items=1, per_item_chars=450)
    related_tests_text = _normalize_optional_value(related_tests_text)

    compact_request_text = _compact_change_request_for_codegen(request.change_request, planner_result)

    def _render(
        module_outline_value: str,
        target_value: str,
        full_file_value: str,
        reference_value: str,
        related_tests_value: str,
        request_value: str,
    ) -> str:
        normalized_module_outline = _normalize_optional_value(module_outline_value)
        normalized_full_file = _normalize_optional_value(full_file_value)
        normalized_reference = _normalize_optional_value(reference_value)
        normalized_related_tests = _normalize_optional_value(related_tests_value)

        prompt = template_text.format(
            operation=request.target.get("operation", "replace_symbol"),
            target_file=request.target.get("file_path", ""),
            target_symbol=request.target.get("qualname", ""),
            insert_after=request.target.get("insert_after") or request.target.get("qualname", "") or "null",
            reference_symbol="null",
            planner_json=_pretty(planner_result),
            request=request_value,
            module_outline_block=_render_optional_block("Структура модуля", normalized_module_outline),
            target_function_block=_render_optional_block("Целевой symbol / anchor", target_value),
            reference_function_block=_render_optional_block("Функция-образец", normalized_reference),
            full_file_source_block=_render_optional_block("Полный исходный текст файла", normalized_full_file),
            related_tests_block=_render_optional_block("Related tests", normalized_related_tests),
        )
        return prompt

    def _drop_reference() -> None:
        nonlocal reference_text, ref_metrics
        reference_text = ""
        ref_metrics = {
            **ref_metrics,
            "reference_count": 0,
            "reference_chars": 0,
            "reference_titles": [],
            "reference_content_modes": [],
        }

    def _drop_related_tests() -> None:
        nonlocal related_tests_text, related_test_metrics
        related_tests_text = ""
        related_test_metrics = {
            **related_test_metrics,
            "related_tests_count": 0,
            "related_test_chars": 0,
            "related_test_qualnames": [],
        }

    trim_steps: list[str] = []
    def _record(step: str) -> None:
        trim_steps.append(step)

    requested_operation = str(request.target.get("operation", "replace_symbol") or "replace_symbol").strip()

    if requested_operation == "insert_after_symbol":
        full_file_text = ""
        _drop_reference()
        _drop_related_tests()
        if module_outline_text:
            module_outline_text, _ = _truncate_text(module_outline_text, 220)
            _record("truncated module_outline to 220 for insert_after_symbol")
        compact_request_text, _ = _truncate_text(compact_request_text, 260)
        _record("truncated request to 260 for insert_after_symbol")
        
    initial_prompt = _render(module_outline_text, target_text, full_file_text, reference_text, related_tests_text, compact_request_text)
    before_trim = len(initial_prompt)

    if len(initial_prompt) > runtime_config.coder_prompt_target_chars and full_file_text:
        full_file_text = ""
        _record("removed full_file_source on soft target limit")
    prompt = _render(module_outline_text, target_text, full_file_text, reference_text, related_tests_text, compact_request_text)

    if len(prompt) > runtime_config.coder_prompt_target_chars and request_mode == "generate" and related_tests_text != "none":
        _drop_related_tests(); _record("removed related_tests on soft target limit for generate")
        prompt = _render(module_outline_text, target_text, full_file_text, reference_text, related_tests_text, compact_request_text)
    if len(prompt) > runtime_config.coder_prompt_target_chars and request_mode != "generate" and reference_text != "none":
        _drop_reference(); _record("removed reference on soft target limit for non-generate")
        prompt = _render(module_outline_text, target_text, full_file_text, reference_text, related_tests_text, compact_request_text)
    if len(prompt) > runtime_config.coder_prompt_target_chars and request_mode != "generate" and related_tests_text != "none":
        _drop_related_tests(); _record("removed related_tests on soft target limit for non-generate")
        prompt = _render(module_outline_text, target_text, full_file_text, reference_text, related_tests_text, compact_request_text)
    if len(prompt) > runtime_config.coder_prompt_target_chars:
        module_outline_text, _ = _truncate_text(module_outline_text, 400); _record("truncated module_outline to 400 on soft target limit")
        prompt = _render(module_outline_text, target_text, full_file_text, reference_text, related_tests_text, compact_request_text)
    if len(prompt) > runtime_config.coder_prompt_hard_limit:
        target_text, _ = _truncate_text(target_text, max(220, runtime_config.coder_prompt_hard_limit // 4)); _record("truncated target on hard limit")
        prompt = _render(module_outline_text, target_text, full_file_text, reference_text, related_tests_text, compact_request_text)
    if len(prompt) > runtime_config.coder_prompt_hard_limit and request_mode == "generate" and related_tests_text != "none":
        _drop_related_tests(); _record("removed related_tests on hard limit for generate")
        prompt = _render(module_outline_text, target_text, full_file_text, reference_text, related_tests_text, compact_request_text)
    if len(prompt) > runtime_config.coder_prompt_hard_limit and reference_text != "none":
        _drop_reference(); _record("removed reference on hard limit")
        prompt = _render(module_outline_text, target_text, full_file_text, reference_text, related_tests_text, compact_request_text)

    runtime_limit = available_user_chars or runtime_config.coder_prompt_hard_limit
    if len(prompt) > runtime_limit and request_mode == "generate" and related_tests_text != "none":
        _drop_related_tests(); _record("removed related_tests on runtime limit for generate")
        prompt = _render(module_outline_text, target_text, full_file_text, reference_text, related_tests_text, compact_request_text)
    if len(prompt) > runtime_limit and request_mode != "generate" and reference_text != "none":
        _drop_reference(); _record("removed reference on runtime limit for non-generate")
        prompt = _render(module_outline_text, target_text, full_file_text, reference_text, related_tests_text, compact_request_text)
    if len(prompt) > runtime_limit:
        compact_request_text, _ = _truncate_text(compact_request_text, max(220, runtime_limit // 5)); _record("truncated request on runtime limit")
        prompt = _render(module_outline_text, target_text, full_file_text, reference_text, related_tests_text, compact_request_text)
    if len(prompt) > runtime_limit:
        target_text, _ = _truncate_text(target_text, max(220, runtime_limit // 4)); _record("truncated target on runtime limit")
        prompt = _render(module_outline_text, target_text, full_file_text, reference_text, related_tests_text, compact_request_text)
    if len(prompt) > runtime_limit and module_outline_text != "[]":
        module_outline_text, _ = _truncate_text(module_outline_text, 120); _record("truncated module_outline to 120 on runtime limit")
        prompt = _render(module_outline_text, target_text, full_file_text, reference_text, related_tests_text, compact_request_text)
    if len(prompt) > runtime_limit and related_tests_text != "none":
        related_tests_text, _ = _truncate_text(related_tests_text, max(180, runtime_limit // 10)); _record("truncated related_tests on runtime limit")
        prompt = _render(module_outline_text, target_text, full_file_text, reference_text, related_tests_text, compact_request_text)
    if len(prompt) > runtime_limit and reference_text != "none":
        _drop_reference(); _record("removed reference on late runtime limit")
        prompt = _render(module_outline_text, target_text, full_file_text, reference_text, related_tests_text, compact_request_text)
    if len(prompt) > runtime_limit:
        compact_request_text, _ = _truncate_text(compact_request_text, 160); _record("truncated request to 160 on late runtime limit")
        prompt = _render(module_outline_text, target_text, full_file_text, reference_text, related_tests_text, compact_request_text)
    if len(prompt) > runtime_limit:
        target_text, _ = _truncate_text(target_text, 160); _record("truncated target to 160 on late runtime limit")
        prompt = _render(module_outline_text, target_text, full_file_text, reference_text, related_tests_text, compact_request_text)

    metrics = _build_coder_prompt_metrics(prompt, target_text, module_outline_text, full_file_text, reference_text, related_tests_text, before_trim, len(prompt), trim_steps)
    metrics.update(ref_metrics)
    metrics.update(related_test_metrics)
    return prompt, metrics


def _build_reference_context_block(reference_context: dict[str, Any], runtime_config: RuntimeConfig | None) -> str:
    max_chars = runtime_config.repair_max_reference_chars if runtime_config else 420
    artifacts = list(reference_context.get("reference_artifacts") or [])[:1]
    compact_reference = {
        "reference_artifacts": [
            {
                "title": item.get("title", ""),
                "usage_mode": item.get("usage_mode", ""),
                "content_mode": item.get("content_mode", ""),
                "content": _truncate_text(str(item.get("content", "") or ""), max_chars)[0],
            }
            for item in artifacts
        ],
    }
    return _pretty(compact_reference)


def _build_repair_extra_blocks(change_request_text: str, constraints: list[str], reference_context_text: str) -> dict[str, str]:
    return {
        "change_request_preserve_block": f"\n\nЗапрос, который нужно сохранить:\n{change_request_text or 'repair request'}",
        "constraints_preserve_block": f"\n\nОграничения:\n{_render_constraints_block(constraints)}",
        "repair_instruction_block": (
            "\n\nИнструкция на исправление:\n"
            "Сделай код валидным и сохрани запрошенное изменение. Не возвращай исходную реализацию и не ослабляй требуемое поведение."
        ),
        "reference_context_block": f"\n\nСправочный контекст:\n{reference_context_text}",
    }


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
    module_outline_text = _render_module_outline(project_context.get("module_outline", []))
    full_file_source = str(project_context.get("full_file_source", "") or "")
    if runtime_config and runtime_config.coder_max_full_file_chars <= 0:
        full_file_source = ""
    elif full_file_source:
        full_file_source, _ = _truncate_text(full_file_source, 700)

    change_request = request.change_request or {}
    change_request_text = _compact_change_request_for_codegen(change_request, None)
    constraints = [str(item) for item in (change_request.get("constraints") or []) if item]
    target_rendered = _render_target_symbol(target_symbol)
    target_rendered, _ = _truncate_text(target_rendered, 900)
    previous_code = str(request.previous_artifact.get("code", "") or "")
    previous_code, _ = _truncate_text(previous_code, 1200)
    reference_context_text = _build_reference_context_block(request.reference_context or {}, runtime_config)
    extra_blocks = _build_repair_extra_blocks(change_request_text, constraints, reference_context_text)

    requested_operation = (
        request.previous_artifact.get("operation")
        or "replace_symbol"
    )
    values = {
        "operation": request.previous_artifact.get("operation", "replace_symbol"),
        "target_file": request.previous_artifact.get("target_file", ""),
        "target_symbol": request.previous_artifact.get("target_qualname", request.previous_artifact.get("target_symbol", "")),
        "insert_after": request.previous_artifact.get("insert_after") or "null",
        "request": change_request_text or "repair request",
        "planner_json": _pretty({"repair_for": request.previous_generation_request_id, "change_request": change_request}),
        "verification_summary": _pretty(request.error_context),
        "verification_summary_json": _pretty(request.error_context),
        "module_outline": module_outline_text,
        "target_function": target_rendered,
        "full_file_source": full_file_source,
        "current_generated_code": previous_code,
        "module_outline_block": _render_optional_block("Module outline", module_outline_text),
        "target_function_block": _render_optional_block("Target function", target_rendered),
        "reference_function_block": "",
        "full_file_source_block": _render_optional_block("Full file source", full_file_source),
        "requested_operation": requested_operation,
        **extra_blocks,
    }
    prompt = template_text.format(**values)

    if runtime_config and len(prompt) > runtime_config.repair_prompt_hard_limit:
        values["reference_context_block"] = "\n\nСправочный контекст:\n" + _pretty({"reference_artifacts": []})
        prompt = template_text.format(**values)
    if runtime_config and len(prompt) > runtime_config.repair_prompt_hard_limit:
        values["module_outline_block"] = ""
        values["full_file_source_block"] = ""
        prompt = template_text.format(**values)
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


def _resolve_test_target_symbol(
    request: GenerationRequest,
    generated_code_artifact: dict[str, Any] | None = None,
) -> tuple[str, str | None]:
    requested_operation = (
        str(request.target.get("operation", "") or "").strip()
        or "replace_symbol"
    )

    anchor_symbol = str(request.target.get("qualname", "") or "").strip()

    if requested_operation != "insert_after_symbol":
        return anchor_symbol, None

    generated_code = ""
    if generated_code_artifact:
        generated_code = str(generated_code_artifact.get("code", "") or "")

    generated_symbol_name = _extract_declared_symbol_name(generated_code)
    if not generated_symbol_name:
        return anchor_symbol, anchor_symbol or None

    target_file = str(request.target.get("file_path", "") or "").strip()
    module_name = target_file[:-3].replace("/", ".") if target_file.endswith(".py") else ""

    effective_symbol = f"{module_name}.{generated_symbol_name}" if module_name else generated_symbol_name
    return effective_symbol, anchor_symbol or None

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
        "source_priority_block": _render_optional_block(
            "Приоритет контекста",
            "Сначала опирайся на связанные тесты, полный исходник файла и явные сигнатуры/импорты; используй generated target-код только если он не противоречит более стабильному проектному контексту."
        ),
        "target_function_block": target_block,
        "full_file_source": full_file_source_text,
        "full_file_source_block": full_file_source_block,
        "generated_test_file": generated_test_file,
        "example_test_source": example_text,
        "example_test_block": example_block,
        "related_tests_block": related_tests_block,
        "import_context_block": import_context_block,
        "inferred_symbols_block": inferred_symbols_block,
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
) -> None:
    logger.info(
        "Test prompt state stage=%s operation=%s prompt_chars=%s available_user_chars=%s "
        "target_chars=%s request_chars=%s example_chars=%s related_tests_chars=%s "
        "has_related_tests=%s import_context_chars=%s inferred_symbols_chars=%s "
        "effective_target_symbol=%s anchor_symbol=%s",
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
    generated_code_artifact: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    pc = request.project_context or {}
    target_symbol = pc.get("target_symbol") or {}
    compact_request_text = _compact_change_request_for_codegen(
        request.change_request,
        planner_result=None,
    )
    effective_target_symbol, anchor_symbol = _resolve_test_target_symbol(
        request,
        generated_code_artifact=generated_code_artifact,
    )

    effective_target_kind = "function"
    if generated_code_artifact and generated_code_artifact.get("code"):
        target_source = str(generated_code_artifact.get("code", "")).strip()
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

    import_context_text = _extract_import_context(full_file_source_text)
    inferred_symbols = _infer_project_symbols(target_source)
    inferred_symbols_text = "\n".join(f"- {name}" for name in inferred_symbols)

    requested_operation = (
        str(request.target.get("operation", "") or "").strip()
        or "replace_symbol"
    )

    trim_steps: list[str] = []

    # Небольшой мягкий запас: лучше сохранить проектный контекст,
    # чем идеально уложиться в лимит, но потерять full_file/related_tests.
    soft_overflow_chars = 350

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
        if related_tests_text:
            _clear_related_tests("removed related_tests for insert_after_symbol")

        if example_text:
            example_text, _ = _truncate_text(example_text, 260)
            _record("truncated example_text to 260 for insert_after_symbol")

        if import_context_text:
            import_context_text, _ = _truncate_text(import_context_text, 220)
            _record("truncated import_context to 220 for insert_after_symbol")

        if inferred_symbols_text:
            inferred_symbols_text, _ = _truncate_text(inferred_symbols_text, 120)
            _record("truncated inferred_symbols to 120 for insert_after_symbol")

        if compact_request_text:
            compact_request_text, _ = _truncate_text(compact_request_text, 180)
            _record("truncated request to 180 for insert_after_symbol")

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
        )
        return template_text.format(**values)

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

    if len(prompt) > available_user_chars and import_context_text:
        import_context_text = ""
        _record("removed import_context on size limit")
        prompt = _render_prompt()
        _log("after_remove_import_context", prompt)

    if len(prompt) > available_user_chars and compact_request_text:
        compact_request_text = ""
        _record("removed compact_request_text on size limit")
        prompt = _render_prompt()
        _log("after_remove_request", prompt)

    # Одна простая попытка ужать related tests, не вводя многоступенчатую схему.
    if len(prompt) > available_user_chars and related_tests_text:
        _truncate_related_tests_once(120, "truncated related_tests once to 120 on size limit")
        prompt = _render_prompt()
        _log("after_truncate_related_tests_once", prompt)

    # Одна простая попытка ужать full file, а не выбрасывать его сразу.
    if len(prompt) > available_user_chars and full_file_source_text:
        _truncate_full_file_once(220, "truncated full_file_source once to 220 on size limit")
        prompt = _render_prompt()
        _log("after_truncate_full_file_once", prompt)

    if len(prompt) > available_user_chars and target_source:
        target_source, _ = _truncate_text(target_source, 180)
        _record("truncated target_source to 180 on size limit")
        prompt = _render_prompt()
        _log("after_truncate_target", prompt)

    # Full file убираем раньше related tests:
    # related tests для тестогенерации обычно ценнее, потому что показывают
    # реальный паттерн создания и использования project objects.
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

    if not full_file_source_text.strip() and not str(related_tests_text or "").strip():
        logger.warning(
            "test prompt degraded: both full_file_source and related_tests were removed; "
            "generation will rely mostly on target code"
        )

    logger.info(
        "test prompt final blocks operation=%s prompt_chars=%s available_user_chars=%s "
        "soft_overflow_chars=%s has_request=%s has_full_file=%s has_example=%s "
        "has_related_tests=%s target_chars=%s request_chars=%s full_file_chars=%s "
        "example_chars=%s related_tests_chars=%s",
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
        "test_has_example_block": bool(example_text),
        "test_has_related_tests_block": bool(str(related_tests_text or "").strip()),
        "test_has_import_context_block": bool(import_context_text),
        "test_has_inferred_symbols_block": bool(inferred_symbols_text),
        "test_has_full_file_context": bool(full_file_source_text),
    }
    return prompt, metrics
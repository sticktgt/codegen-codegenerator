# codegenerator/prompts/prompt_builder.py
from __future__ import annotations

import ast
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


def _extract_import_block_from_source(source_text: str) -> str:
    if not source_text:
        return ""
    lines: list[str] = []
    for raw_line in source_text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.startswith('import ') or stripped.startswith('from '):
            lines.append(line)
    return "\n".join(lines)


def _infer_project_symbol_names_from_source(source_text: str) -> list[str]:
    if not source_text:
        return []
    try:
        tree = ast.parse(source_text)
    except SyntaxError:
        return []

    names: set[str] = set()

    class Visitor(ast.NodeVisitor):
        def visit_Name(self, node: ast.Name) -> None:
            if node.id and node.id[:1].isupper():
                names.add(node.id)
            self.generic_visit(node)

        def visit_arg(self, node: ast.arg) -> None:
            annotation = getattr(node, 'annotation', None)
            if isinstance(annotation, ast.Name) and annotation.id[:1].isupper():
                names.add(annotation.id)
            self.generic_visit(node)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            returns = getattr(node, 'returns', None)
            if isinstance(returns, ast.Name) and returns.id[:1].isupper():
                names.add(returns.id)
            self.generic_visit(node)

    Visitor().visit(tree)
    return sorted(names)

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
    return {
        "coder_prompt_chars_before_trim": before_trim,
        "coder_prompt_chars_after_trim": after_trim,
        "coder_target_chars": len(target_text),
        "coder_module_outline_chars": len(module_outline_text),
        "coder_full_file_chars": len(full_file_text),
        "coder_reference_chars": _reference_text_chars(reference_text),
        "coder_related_test_chars": 0 if related_tests_text == "none" else len(related_tests_text),
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
    request_mode = str(getattr(request, 'mode', 'generate') or 'generate')
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
    related_tests_text, related_test_metrics = _render_related_tests(
        pc,
        max_items=runtime_config.prompt_assembly.coder_related_tests_max_items,
        per_item_chars=runtime_config.prompt_assembly.coder_related_tests_per_item_chars,
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
        related_tests_value: str,
        request_value: str,
    ) -> str:
        prompt = template_text.format(
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
        if related_tests_value != "none":
            prompt += "\n\nRelated tests:\n" + related_tests_value
        return prompt

    def _drop_reference() -> None:
        nonlocal reference_text, ref_metrics
        reference_text = "none"
        ref_metrics = {
            **ref_metrics,
            "reference_count": 0,
            "reference_chars": 0,
            "reference_titles": [],
            "reference_content_modes": [],
        }

    def _drop_related_tests() -> None:
        nonlocal related_tests_text, related_test_metrics
        related_tests_text = "none"
        related_test_metrics = {
            **related_test_metrics,
            "related_tests_count": 0,
            "related_test_chars": 0,
            "related_test_qualnames": [],
        }

    trim_steps: list[str] = []

    def _record(step: str) -> None:
        trim_steps.append(step)

    initial_prompt = _render(
        module_outline_text,
        target_text,
        full_file_text,
        reference_text,
        related_tests_text,
        compact_request_text,
    )
    before_trim = len(initial_prompt)

    if len(initial_prompt) > runtime_config.coder_prompt_target_chars and full_file_text:
        full_file_text = ""
        _record("removed full_file_source on soft target limit")
    prompt = _render(
        module_outline_text,
        target_text,
        full_file_text,
        reference_text,
        related_tests_text,
        compact_request_text,
    )

    # Для generate стараемся держать reference дольше, а related tests считаем опциональными.
    # Для других режимов (если будут использовать этот builder) порядок остается консервативным.
    if len(prompt) > runtime_config.coder_prompt_target_chars and request_mode == "generate" and related_tests_text != "none":
        _drop_related_tests()
        _record("removed related_tests on soft target limit for generate")
        prompt = _render(
            module_outline_text,
            target_text,
            full_file_text,
            reference_text,
            related_tests_text,
            compact_request_text,
        )

    if len(prompt) > runtime_config.coder_prompt_target_chars and request_mode != "generate" and reference_text != "none":
        _drop_reference()
        _record("removed reference on soft target limit for non-generate")
        prompt = _render(
            module_outline_text,
            target_text,
            full_file_text,
            reference_text,
            related_tests_text,
            compact_request_text,
        )

    if len(prompt) > runtime_config.coder_prompt_target_chars and request_mode != "generate" and related_tests_text != "none":
        _drop_related_tests()
        _record("removed related_tests on soft target limit for non-generate")
        prompt = _render(
            module_outline_text,
            target_text,
            full_file_text,
            reference_text,
            related_tests_text,
            compact_request_text,
        )

    # Для generate не удаляем reference на soft target этапе.
    # Сначала пытаемся ужать module outline и только на более поздних fallback-этапах
    # допускаем удаление reference, если prompt все еще не помещается.

    if len(prompt) > runtime_config.coder_prompt_target_chars:
        module_outline_text, _ = _truncate_text(module_outline_text, runtime_config.prompt_assembly.coder_soft_module_outline_chars)
        _record(f"truncated module_outline to {runtime_config.prompt_assembly.coder_soft_module_outline_chars} on soft target limit")
        prompt = _render(
            module_outline_text,
            target_text,
            full_file_text,
            reference_text,
            related_tests_text,
            compact_request_text,
        )

    if len(prompt) > runtime_config.coder_prompt_hard_limit:
        target_text, _ = _truncate_text(
            target_text,
            max(220, runtime_config.coder_prompt_hard_limit // 4),
        )
        _record("truncated target on hard limit")
        prompt = _render(
            module_outline_text,
            target_text,
            full_file_text,
            reference_text,
            related_tests_text,
            compact_request_text,
        )

    if len(prompt) > runtime_config.coder_prompt_hard_limit and request_mode == "generate" and related_tests_text != "none":
        _drop_related_tests()
        _record("removed related_tests on hard limit for generate")
        prompt = _render(
            module_outline_text,
            target_text,
            full_file_text,
            reference_text,
            related_tests_text,
            compact_request_text,
        )

    if len(prompt) > runtime_config.coder_prompt_hard_limit and reference_text != "none":
        _drop_reference()
        _record("removed reference on hard limit")
        prompt = _render(
            module_outline_text,
            target_text,
            full_file_text,
            reference_text,
            related_tests_text,
            compact_request_text,
        )

    runtime_limit = available_user_chars or runtime_config.coder_prompt_hard_limit

    # Для generate не удаляем related_tests на раннем runtime_limit этапе.
    # Сначала пробуем ужать request/target/module outline, а related tests сокращаем позже.

    # Для generate не удаляем reference на раннем runtime_limit этапе.
    # Сначала даем шанс более мягкому ужатию request/target/module_outline.
    # Reference остается последним fallback на позднем runtime этапе.
    if len(prompt) > runtime_limit and request_mode != "generate" and reference_text != "none":
        _drop_reference()
        _record("removed reference on runtime limit for non-generate")
        prompt = _render(
            module_outline_text,
            target_text,
            full_file_text,
            reference_text,
            related_tests_text,
            compact_request_text,
        )

    if len(prompt) > runtime_limit:
        compact_request_text, _ = _truncate_text(
            compact_request_text,
            max(runtime_config.prompt_assembly.coder_runtime_request_chars, runtime_limit // 5),
        )
        _record("truncated request on runtime limit")
        prompt = _render(
            module_outline_text,
            target_text,
            full_file_text,
            reference_text,
            related_tests_text,
            compact_request_text,
        )

    if len(prompt) > runtime_limit:
        target_text, _ = _truncate_text(
            target_text,
            max(runtime_config.prompt_assembly.coder_runtime_target_chars, runtime_limit // 4),
        )
        _record("truncated target on runtime limit")
        prompt = _render(
            module_outline_text,
            target_text,
            full_file_text,
            reference_text,
            related_tests_text,
            compact_request_text,
        )

    if len(prompt) > runtime_limit and module_outline_text != "[]":
        module_outline_text, _ = _truncate_text(module_outline_text, runtime_config.prompt_assembly.coder_runtime_module_outline_chars)
        _record(f"truncated module_outline to {runtime_config.prompt_assembly.coder_runtime_module_outline_chars} on runtime limit")
        prompt = _render(
            module_outline_text,
            target_text,
            full_file_text,
            reference_text,
            related_tests_text,
            compact_request_text,
        )

    if len(prompt) > runtime_limit and related_tests_text != "none":
        related_tests_text, _ = _truncate_text(
            related_tests_text,
            max(runtime_config.prompt_assembly.coder_runtime_related_tests_min_chars, runtime_limit // 10),
        )
        _record("truncated related_tests on runtime limit")
        prompt = _render(
            module_outline_text,
            target_text,
            full_file_text,
            reference_text,
            related_tests_text,
            compact_request_text,
        )

    if len(prompt) > runtime_limit and reference_text != "none":
        _drop_reference()
        _record("removed reference on late runtime limit")
        prompt = _render(
            module_outline_text,
            target_text,
            full_file_text,
            reference_text,
            related_tests_text,
            compact_request_text,
        )

    if len(prompt) > runtime_limit:
        compact_request_text, _ = _truncate_text(compact_request_text, runtime_config.prompt_assembly.coder_runtime_request_chars)
        _record(f"truncated request to {runtime_config.prompt_assembly.coder_runtime_request_chars} on late runtime limit")
        prompt = _render(
            module_outline_text,
            target_text,
            full_file_text,
            reference_text,
            related_tests_text,
            compact_request_text,
        )

    if len(prompt) > runtime_limit:
        target_text, _ = _truncate_text(target_text, runtime_config.prompt_assembly.coder_runtime_target_chars)
        _record(f"truncated target to {runtime_config.prompt_assembly.coder_runtime_target_chars} on late runtime limit")
        prompt = _render(
            module_outline_text,
            target_text,
            full_file_text,
            reference_text,
            related_tests_text,
            compact_request_text,
        )

    if len(prompt) > runtime_limit and related_tests_text != "none":
        _drop_related_tests()
        _record("removed related_tests on final runtime fallback")
        prompt = _render(
            module_outline_text,
            target_text,
            full_file_text,
            reference_text,
            related_tests_text,
            compact_request_text,
        )

    metrics = _build_coder_prompt_metrics(
        prompt,
        target_text,
        module_outline_text,
        full_file_text,
        reference_text,
        related_tests_text,
        before_trim,
        len(prompt),
        trim_steps,
    )
    metrics.update(ref_metrics)
    metrics.update(related_test_metrics)
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
    target_source, _ = _truncate_text(target_source, runtime_config.prompt_assembly.repair_target_source_chars)
    module_outline_text = _render_module_outline(module_outline)

    previous_code = str(request.previous_artifact.get("code", "") or "")
    previous_code, _ = _truncate_text(previous_code, runtime_config.prompt_assembly.repair_previous_code_chars)

    if runtime_config and runtime_config.coder_max_full_file_chars <= 0:
        full_file_source = ""
    elif full_file_source:
        full_file_source, _ = _truncate_text(full_file_source, runtime_config.prompt_assembly.repair_full_file_source_chars)

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

    full_file_source = str(pc.get("full_file_source", "") or "").strip()
    import_block = _extract_import_block_from_source(full_file_source)
    inferred_project_symbols = _infer_project_symbol_names_from_source(target_source)

    example_text, _ = _truncate_text(example_test_source or "", runtime_config.prompt_assembly.test_example_chars)
    related_tests_text, related_test_metrics = _render_related_tests(
        pc,
        max_items=1,
        per_item_chars=runtime_config.budget_strategy.generate_test_related_test_source_limit,
    )

    def _render(
        *,
        request_value: str,
        target_function_value: str,
        example_value: str,
        related_tests_value: str,
    ) -> str:
        example_block = f"\n\nExample test:\n{example_value}" if example_value else ""
        target_block = (
            f"\n\nGenerated target code:\n{target_function_value}"
            if target_function_value
            else ""
        )
        related_tests_block = (
            f"\n\nExisting related tests:\n{related_tests_value}"
            if related_tests_value and related_tests_value != "none"
            else ""
        )
        import_block_text = f"\n\nTarget file imports:\n{import_block}" if import_block else ""
        inferred_symbols_block = (
            "\n\nProject symbols referenced in target code (import them if used in the test):\n" + "\n".join(f"- {name}" for name in inferred_project_symbols)
            if inferred_project_symbols
            else ""
        )
        prompt = template_text.format(
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
        return prompt + import_block_text + inferred_symbols_block + related_tests_block

    prompt = _render(
        request_value=compact_request_text,
        target_function_value=target_source,
        example_value=example_text,
        related_tests_value=related_tests_text,
    )
    before_trim = len(prompt)

    if len(prompt) > available_user_chars:
        example_text, _ = _truncate_text(example_text, runtime_config.prompt_assembly.test_example_trim_chars)
        prompt = _render(
            request_value=compact_request_text,
            target_function_value=target_source,
            example_value=example_text,
            related_tests_value=related_tests_text,
        )

    if len(prompt) > available_user_chars and related_tests_text != "none":
        related_tests_text = "none"
        related_test_metrics = {
            **related_test_metrics,
            "related_tests_count": 0,
            "related_test_chars": 0,
            "related_test_qualnames": [],
        }
        prompt = _render(
            request_value=compact_request_text,
            target_function_value=target_source,
            example_value=example_text,
            related_tests_value=related_tests_text,
        )

    if len(prompt) > available_user_chars:
        target_source, _ = _truncate_text(target_source, runtime_config.prompt_assembly.repair_target_source_chars)
        prompt = _render(
            request_value=compact_request_text,
            target_function_value=target_source,
            example_value=example_text,
            related_tests_value=related_tests_text,
        )

    if len(prompt) > available_user_chars:
        target_source, _ = _truncate_text(target_source, runtime_config.prompt_assembly.test_target_trim_second_chars)
        example_text, _ = _truncate_text(example_text, runtime_config.prompt_assembly.test_example_trim_second_chars)
        compact_request_text, _ = _truncate_text(compact_request_text, runtime_config.prompt_assembly.test_request_trim_first_chars)
        prompt = _render(
            request_value=compact_request_text,
            target_function_value=target_source,
            example_value=example_text,
            related_tests_value=related_tests_text,
        )

    if len(prompt) > available_user_chars and related_tests_text != "none":
        related_tests_text, _ = _truncate_text(
            related_tests_text,
            max(runtime_config.prompt_assembly.test_related_tests_trim_min_chars, available_user_chars // 10),
        )
        prompt = _render(
            request_value=compact_request_text,
            target_function_value=target_source,
            example_value=example_text,
            related_tests_value=related_tests_text,
        )

    if len(prompt) > available_user_chars:
        compact_request_text, _ = _truncate_text(compact_request_text, runtime_config.prompt_assembly.coder_runtime_request_chars)
        target_source, _ = _truncate_text(target_source, 420)
        example_text, _ = _truncate_text(example_text, 120)
        prompt = _render(
            request_value=compact_request_text,
            target_function_value=target_source,
            example_value=example_text,
            related_tests_value=related_tests_text,
        )

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
        "test_import_context_chars": len(import_block),
        "test_inferred_project_symbols": inferred_project_symbols,
    }
    return prompt, metrics

from __future__ import annotations

from dataclasses import replace
from typing import Any


def _safe_len(value: str | None) -> int:
    return len(value or "")


def _truncate_text(text: str | None, limit: int) -> tuple[str, bool]:
    if not text:
        return "", False
    if len(text) <= limit:
        return text, False
    head = max(0, limit - 40)
    return f"{text[:head]}\n\n# ... truncated, original_chars={len(text)}", True


def _sum_reference_chars(reference_artifacts: list[dict[str, Any]] | None) -> int:
    total = 0
    for item in reference_artifacts or []:
        total += len(str(item.get("content", "")))
    return total


def _context_metrics_from_request(request: dict[str, Any]) -> dict[str, Any]:
    project_context = request.get("project_context", {}) or {}
    reference_context = request.get("reference_context", {}) or {}

    target_symbol = project_context.get("target_symbol", {}) or {}
    related_tests = project_context.get("related_tests", []) or []
    reference_artifacts = reference_context.get("reference_artifacts", []) or []

    return {
        "target_source_chars": len(str(target_symbol.get("source", ""))),
        "full_file_chars": len(str(project_context.get("full_file_source", ""))),
        "related_tests_count": len(related_tests),
        "related_test_chars": sum(len(str(t.get("source", ""))) for t in related_tests),
        "reference_artifacts_count": len(reference_artifacts),
        "reference_chars": _sum_reference_chars(reference_artifacts),
    }


def _drop_all_reference_artifacts(request: dict[str, Any], trim_log: list[str]) -> None:
    reference_context = request.setdefault("reference_context", {})
    artifacts = reference_context.get("reference_artifacts", []) or []
    if artifacts:
        trim_log.append(
            f"removed all reference_artifacts: {len(artifacts)} items, chars={_sum_reference_chars(artifacts)}"
        )
    reference_context["reference_artifacts"] = []


def _keep_single_test_example(request: dict[str, Any], trim_log: list[str]) -> None:
    reference_context = request.setdefault("reference_context", {})
    artifacts = reference_context.get("reference_artifacts", []) or []
    if not artifacts:
        return
    kept = artifacts[:1]
    removed = artifacts[1:]
    if removed:
        trim_log.append(
            f"trimmed reference_artifacts for generate-test: {len(artifacts)} -> 1"
        )
    reference_context["reference_artifacts"] = kept


def _trim_module_outline(request: dict[str, Any], keep: int, trim_log: list[str]) -> None:
    project_context = request.setdefault("project_context", {})
    module_outline = project_context.get("module_outline", []) or []
    if len(module_outline) > keep:
        trim_log.append(f"trimmed module_outline: {len(module_outline)} -> {keep}")
        project_context["module_outline"] = module_outline[:keep]


def _trim_related_tests(request: dict[str, Any], keep: int, source_limit: int, trim_log: list[str]) -> None:
    project_context = request.setdefault("project_context", {})
    related_tests = project_context.get("related_tests", []) or []
    original_count = len(related_tests)

    if len(related_tests) > keep:
        trim_log.append(f"trimmed related_tests count: {len(related_tests)} -> {keep}")
        related_tests = related_tests[:keep]

    if keep <= 0 or source_limit <= 0:
        if related_tests:
            trim_log.append(f"removed related_tests content: {len(related_tests)} -> 0")
        project_context["related_tests"] = []
        return

    kept_items: list[dict[str, Any]] = []
    removed_for_size = 0
    removed_chars = 0
    for item in related_tests:
        source = str(item.get("source", ""))
        if source_limit > 0 and len(source) > source_limit:
            removed_for_size += 1
            removed_chars += len(source)
            continue
        new_item = dict(item)
        new_item["source"] = source
        new_item["truncated"] = False
        kept_items.append(new_item)

    if removed_for_size:
        trim_log.append(
            f"removed oversized related_tests: {len(kept_items) + removed_for_size} -> {len(kept_items)}, removed_chars={removed_chars}, per_test_limit={source_limit}"
        )
    elif original_count != len(kept_items):
        trim_log.append(f"trimmed related_tests count: {original_count} -> {len(kept_items)}")

    project_context["related_tests"] = kept_items


def _trim_target_source(request: dict[str, Any], source_limit: int, trim_log: list[str]) -> None:
    project_context = request.setdefault("project_context", {})
    target_symbol = project_context.setdefault("target_symbol", {})
    source = str(target_symbol.get("source", ""))
    new_source, truncated = _truncate_text(source, source_limit)
    if truncated:
        trim_log.append(f"trimmed target_symbol.source: {len(source)} -> {len(new_source)}")
        target_symbol["source"] = new_source
        target_symbol["truncated"] = True


def _trim_previous_artifact(request: dict[str, Any], code_limit: int, trim_log: list[str]) -> None:
    previous_artifact = request.get("previous_artifact") or {}
    code = str(previous_artifact.get("code", ""))
    new_code, truncated = _truncate_text(code, code_limit)
    if truncated:
        trim_log.append(f"trimmed previous_artifact.code: {len(code)} -> {len(new_code)}")
        previous_artifact["code"] = new_code


def _trim_verification_summary(request: dict[str, Any], message_limit: int, trim_log: list[str]) -> None:
    error_context = request.get("error_context") or {}
    verification_summary = error_context.get("verification_summary") or {}
    messages = verification_summary.get("messages") or []
    if not messages:
        return
    new_messages: list[str] = []
    total_before = sum(len(str(m)) for m in messages)
    for msg in messages[:2]:
        new_msg, _ = _truncate_text(str(msg), message_limit)
        new_messages.append(new_msg)
    verification_summary["messages"] = new_messages
    total_after = sum(len(str(m)) for m in new_messages)
    if total_after < total_before:
        trim_log.append(f"trimmed verification_summary.messages: {total_before} -> {total_after}")


def apply_budget_strategy(
    request: dict[str, Any],
    mode: str,
    request_chars_limit: int,
    logger,
    config,
) -> tuple[dict[str, Any], list[str]]:
    trim_log: list[str] = []

    # shallow-deep enough copy for our fields
    request = {
        **request,
        "project_context": dict(request.get("project_context") or {}),
        "reference_context": dict(request.get("reference_context") or {}),
        "options": dict(request.get("options") or {}),
    }

    project_context = request["project_context"]
    reference_context = request["reference_context"]

    if "target_symbol" in project_context:
        project_context["target_symbol"] = dict(project_context["target_symbol"] or {})
    if "related_tests" in project_context:
        project_context["related_tests"] = [dict(x) for x in (project_context.get("related_tests") or [])]
    if "module_outline" in project_context:
        project_context["module_outline"] = list(project_context.get("module_outline") or [])
    if "reference_artifacts" in reference_context:
        reference_context["reference_artifacts"] = [dict(x) for x in (reference_context.get("reference_artifacts") or [])]

    metrics_before = _context_metrics_from_request(request)

    budget = config.budget_strategy

    if mode == "generate_test":
        if budget.generate_test_drop_reference:
            _drop_all_reference_artifacts(request, trim_log)
        _trim_module_outline(request, keep=budget.generate_test_module_outline_keep, trim_log=trim_log)
        _trim_related_tests(
            request,
            keep=budget.generate_test_related_tests_keep,
            source_limit=budget.generate_test_related_test_source_limit,
            trim_log=trim_log,
        )
        _trim_target_source(request, source_limit=budget.generate_test_target_source_limit, trim_log=trim_log)

    elif mode == "repair":
        if budget.repair_drop_reference:
            _drop_all_reference_artifacts(request, trim_log)
        _trim_module_outline(request, keep=budget.repair_module_outline_keep, trim_log=trim_log)
        _trim_verification_summary(request, message_limit=budget.repair_verification_message_limit, trim_log=trim_log)
        _trim_previous_artifact(request, code_limit=budget.repair_previous_artifact_code_limit, trim_log=trim_log)
        _trim_related_tests(
            request,
            keep=budget.repair_related_tests_keep,
            source_limit=budget.repair_related_test_source_limit,
            trim_log=trim_log,
        )
        _trim_target_source(request, source_limit=budget.repair_target_source_limit, trim_log=trim_log)

    else:  # generate
        _trim_module_outline(request, keep=budget.generate_module_outline_keep, trim_log=trim_log)
        _trim_related_tests(
            request,
            keep=budget.generate_related_tests_keep,
            source_limit=budget.generate_related_test_source_limit,
            trim_log=trim_log,
        )
        _trim_target_source(request, source_limit=budget.generate_target_source_limit, trim_log=trim_log)

    metrics_after = _context_metrics_from_request(request)
    request["context_metrics"] = {
        **metrics_after,
        "request_chars_limit": request_chars_limit,
        "budget_trim_applied": bool(trim_log),
        "budget_trim_log": trim_log,
    }

    logger.info(
        "context budget mode=%s limit=%s before=%s after=%s trim_steps=%s",
        mode,
        request_chars_limit,
        metrics_before,
        metrics_after,
        trim_log,
    )

    return request, trim_log
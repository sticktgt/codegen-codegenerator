from __future__ import annotations

import ast
import json
import re
import textwrap
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
    *,
    strip_source_docstrings: bool = False,
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
        if strip_source_docstrings and source:
            source, _ = _strip_docstrings_from_python_source(source)
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
    *,
    strip_source_docstrings: bool = False,
) -> tuple[str, dict[str, Any]]:
    artifacts = list(reference_context.get("reference_artifacts") or [])[:max_items]
    blocks: list[str] = []
    total_chars = 0
    titles: list[str] = []
    content_modes: list[str] = []

    for item in artifacts:
        raw_content = str(item.get("content", ""))
        content = raw_content
        if strip_source_docstrings and content:
            content, _ = _strip_docstrings_from_python_source(content)
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





def _render_allowed_api_surface(
    project_context: dict[str, Any],
    max_chars: int = 1600,
) -> tuple[str, dict[str, Any]]:
    surface = project_context.get("allowed_api_surface") or {}
    dependencies = list(surface.get("dependencies") or [])
    free_functions = list(surface.get("free_functions") or [])

    compact_dependencies: list[dict[str, Any]] = []
    for dep in dependencies:
        methods: list[dict[str, Any]] = []
        for method in dep.get("allowed_methods") or []:
            if isinstance(method, dict):
                methods.append(
                    {
                        "name": method.get("name", ""),
                        "signature": method.get("signature", ""),
                        "qualname": method.get("qualname", ""),
                    }
                )
        if methods:
            compact_dependencies.append(
                {
                    "access_path": dep.get("access_path", ""),
                    "type_name": dep.get("type_name", ""),
                    "source": dep.get("source", ""),
                    "allowed_methods": methods,
                    "origin_examples": list(dep.get("origin_examples") or [])[:3],
                }
            )

    compact_free_functions: list[dict[str, Any]] = []
    for item in free_functions:
        if isinstance(item, dict):
            compact_free_functions.append(
                {
                    "name": item.get("name", ""),
                    "signature": item.get("signature", ""),
                    "qualname": item.get("qualname", ""),
                    "origin_qualname": item.get("origin_qualname", ""),
                }
            )

    if not compact_dependencies and not compact_free_functions:
        return "none", {
            "allowed_api_surface_dependencies": 0,
            "allowed_api_surface_free_functions": 0,
            "allowed_api_surface_chars": 0,
            "allowed_api_surface_original_chars": 0,
        }

    rendered = _pretty({"dependencies": compact_dependencies, "free_functions": compact_free_functions})
    original_chars = len(rendered)
    if max_chars > 0 and len(rendered) > max_chars:
        rendered, _ = _truncate_text(rendered, max_chars)

    return rendered, {
        "allowed_api_surface_dependencies": len(compact_dependencies),
        "allowed_api_surface_free_functions": len(compact_free_functions),
        "allowed_api_surface_chars": len(rendered),
        "allowed_api_surface_original_chars": original_chars,
    }


def _call_display_name_from_prompt(func: Any) -> str:
    import ast

    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        parts = [func.attr]
        value = func.value
        while isinstance(value, ast.Attribute):
            parts.append(value.attr)
            value = value.value
        if isinstance(value, ast.Name):
            parts.append(value.id)
        return ".".join(reversed(parts))
    return ""


def _visible_return_fields_from_contracts(project_context: dict[str, Any]) -> dict[str, list[str]]:
    import ast

    fields_by_type: dict[str, set[str]] = {}

    for item in _contract_symbols_from_project_context(project_context):
        source = str(item.get("source_excerpt") or item.get("source_code") or item.get("source") or "")
        if not source:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Call):
                type_name = ""
                if isinstance(node.value.func, ast.Name):
                    type_name = node.value.func.id
                elif isinstance(node.value.func, ast.Attribute):
                    type_name = _call_display_name_from_prompt(node.value.func).rsplit(".", 1)[-1]
                if not type_name:
                    continue
                fields = {kw.arg for kw in node.value.keywords if kw.arg}
                if fields:
                    fields_by_type.setdefault(type_name, set()).update(fields)

        if str(item.get("kind") or "") == "class":
            type_name = str(item.get("name") or item.get("qualname", "").rsplit(".", 1)[-1])
            class_fields: set[str] = set()
            for node in getattr(tree, "body", []):
                if isinstance(node, ast.ClassDef):
                    for child in node.body:
                        if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                            class_fields.add(child.target.id)
                        elif isinstance(child, ast.Assign):
                            for target in child.targets:
                                if isinstance(target, ast.Name):
                                    class_fields.add(target.id)
            if type_name and class_fields:
                fields_by_type.setdefault(type_name, set()).update(class_fields)

    return {name: sorted(fields) for name, fields in fields_by_type.items()}


def _method_doc_summary(docstring: str, max_chars: int = 120) -> str:
    doc = " ".join(str(docstring or "").strip().split())
    if not doc:
        return ""
    if len(doc) <= max_chars:
        return doc
    return doc[: max_chars - 1].rstrip() + "…"


def _method_display_signature(item: dict[str, Any]) -> str:
    signature = str(item.get("signature") or "").strip()
    if signature:
        return signature
    name = str(item.get("name") or "").strip()
    if name:
        return f"def {name}(...)"
    qualname = str(item.get("qualname") or "").strip()
    return qualname or "method"


def _same_class_method_priority(item: dict[str, Any]) -> tuple[int, int, str]:
    """Order same-class methods so useful helpers are visible before truncation.

    This order is intentionally not a hard recommendation. It only prevents
    long class lifecycle methods such as __init__ from hiding small helper
    methods when the prompt budget is tight.
    """
    name = str(item.get("name") or item.get("qualname") or "").lower()
    if any(token in name for token in ("find", "lookup", "locate", "resolve")):
        group = 0
    elif "search" in name:
        group = 1
    elif any(token in name for token in ("load", "read", "open", "parse")):
        group = 2
    elif any(token in name for token in ("get", "build", "make", "create")):
        group = 3
    elif any(token in name for token in ("save", "write", "dump", "serialize")):
        group = 4
    elif name.startswith("__"):
        group = 9
    else:
        group = 5
    return (group, len(name), name)


def _render_same_class_methods(project_context: dict[str, Any], max_chars: int = 1200) -> tuple[str, dict[str, Any]]:
    methods = [item for item in (project_context.get("same_class_methods") or []) if isinstance(item, dict)]
    if not methods:
        return "none", {"same_class_methods_count": 0, "same_class_methods_chars": 0}

    ordered_methods = sorted(methods, key=_same_class_method_priority)
    method_names = []
    for item in ordered_methods:
        name = str(item.get("name") or "").strip()
        qualname = str(item.get("qualname") or "").strip()
        method_names.append(name or qualname or _method_display_signature(item))

    summary_lines: list[str] = [
        "Краткий список видимых методов того же класса:",
        "Методы: " + ", ".join(method_names),
    ]

    # Render compact details in priority order. A one-line method name list is
    # already present above, so even tight truncation keeps all available helper
    # method names visible to the model.
    for item in ordered_methods:
        qualname = str(item.get("qualname") or "").strip()
        signature = _method_display_signature(item)
        doc = _method_doc_summary(str(item.get("docstring") or ""), max_chars=70)
        prefix = f"- {qualname}" if qualname else f"- {signature}"
        details = [prefix]
        if signature and signature != qualname:
            details.append(f"сигнатура: {signature}")
        if doc:
            details.append(f"описание: {doc}")
        summary_lines.append("; ".join(details))

    # Source excerpts are useful, but they must not hide the compact list above.
    # Therefore excerpts are shown only for a few likely-relevant methods and after
    # all method names and signatures have already been listed.
    excerpt_lines: list[str] = []
    excerpt_budget = max(0, max_chars - len("\n".join(summary_lines)) - 120)
    if excerpt_budget > 220:
        excerpt_lines.append("Короткие фрагменты наиболее релевантных методов того же класса:")
        selected = ordered_methods[:3]
        per_method_budget = max(140, min(320, excerpt_budget // max(1, len(selected))))
        for item in selected:
            source = str(item.get("source_excerpt") or "").strip()
            if not source:
                continue
            qualname = str(item.get("qualname") or item.get("name") or "method").strip()
            if len(source) > per_method_budget:
                source = source[: per_method_budget - 1].rstrip() + "…"
            excerpt_lines.append(f"- {qualname}:")
            excerpt_lines.append(source)

    rendered = "\n".join(summary_lines + excerpt_lines).strip() or "none"
    original_chars = 0 if rendered == "none" else len(rendered)
    if max_chars > 0 and rendered != "none" and len(rendered) > max_chars:
        # Prefer preserving the method-name line and as many compact details as fit.
        kept_lines: list[str] = []
        running = 0
        for line in summary_lines:
            proposed = running + len(line) + (1 if kept_lines else 0)
            if proposed > max_chars:
                break
            kept_lines.append(line)
            running = proposed
        rendered = "\n".join(kept_lines).strip()
        if not rendered:
            rendered, _ = _truncate_text("\n".join(summary_lines), max_chars)
    return rendered, {
        "same_class_methods_count": len(methods),
        "same_class_methods_chars": len(rendered) if rendered != "none" else 0,
        "same_class_methods_original_chars": original_chars,
    }


def _render_reuse_existing_logic(project_context: dict[str, Any], max_chars: int = 700) -> tuple[str, dict[str, Any]]:
    reuse = project_context.get("reuse_existing_logic") or {}
    if not isinstance(reuse, dict):
        return "none", {"reuse_existing_logic_contracts": 0, "reuse_existing_logic_chars": 0}
    mode = str(reuse.get("mode") or "none").strip()
    contracts = [item for item in (reuse.get("contracts") or []) if isinstance(item, dict)]
    if mode == "none" or not contracts:
        return "none", {"reuse_existing_logic_contracts": 0, "reuse_existing_logic_chars": 0}
    lines = [
        f"Режим: {mode}",
        f"Уверенность: {reuse.get('confidence', 0)}",
    ]
    reason = str(reuse.get("reason") or "").strip()
    if reason:
        lines.append(f"Причина: {reason}")
    lines.append("Существующая логика, которую следует рассмотреть для переиспользования:")
    for item in contracts:
        qualname = str(item.get("qualname") or "").strip()
        if not qualname:
            continue
        role = str(item.get("role") or "").strip()
        item_reason = str(item.get("reason") or "").strip()
        suffix = f" ({role})" if role else ""
        lines.append(f"- {qualname}{suffix}")
        if item_reason:
            lines.append(f"  Причина: {item_reason}")
    rendered = "\n".join(lines).strip() or "none"
    original_chars = 0 if rendered == "none" else len(rendered)
    if max_chars > 0 and rendered != "none" and len(rendered) > max_chars:
        rendered, _ = _truncate_text(rendered, max_chars)
    return rendered, {
        "reuse_existing_logic_contracts": len(contracts),
        "reuse_existing_logic_chars": len(rendered) if rendered != "none" else 0,
        "reuse_existing_logic_original_chars": original_chars,
    }


def _render_visible_implementation_facts(
    project_context: dict[str, Any],
    max_chars: int = 1800,
) -> tuple[str, dict[str, Any]]:
    allowed_text, allowed_metrics = _render_allowed_api_surface(project_context, max_chars=max_chars)
    required_contracts_text, required_contracts_metrics = _render_required_contracts(project_context, max_chars=max(600, max_chars // 2))
    required_members_text, required_members_metrics = _render_required_class_members(project_context, max_chars=max(600, max_chars // 2))
    model_surfaces_text, model_surfaces_metrics = _render_model_surfaces(project_context, max_chars=max(700, max_chars // 2))
    same_class_methods_text, same_class_methods_metrics = _render_same_class_methods(project_context, max_chars=max(700, max_chars // 2))
    reuse_existing_logic_text, reuse_existing_logic_metrics = _render_reuse_existing_logic(project_context, max_chars=max(500, max_chars // 3))
    fields_by_type = _visible_return_fields_from_contracts(project_context)

    facts: list[str] = []
    if model_surfaces_text and model_surfaces_text != "none":
        facts.append("Visible model surfaces (valid fields and constructor arguments):")
        facts.append(model_surfaces_text)

    if allowed_text and allowed_text != "none":
        facts.append("Allowed calls:")
        facts.append(allowed_text)

    if required_contracts_text and required_contracts_text != "none":
        facts.append("Required production contract calls (must be used by generated code):")
        facts.append(required_contracts_text)

    if required_members_text and required_members_text != "none":
        facts.append("Required class members for class replacement (must be preserved unless explicitly removed by user):")
        facts.append(required_members_text)

    if same_class_methods_text and same_class_methods_text != "none":
        facts.append("Видимые методы того же класса:")
        facts.append(same_class_methods_text)

    if reuse_existing_logic_text and reuse_existing_logic_text != "none":
        facts.append("Подсказки по переиспользованию существующих методов проекта:")
        facts.append(reuse_existing_logic_text)

    if fields_by_type:
        facts.append("Visible return fields:")
        for type_name, fields in fields_by_type.items():
            facts.append(f"- {type_name}: {', '.join(fields)}")

    rendered = "\n".join(facts) if facts else "none"
    original_chars = len(rendered) if rendered != "none" else 0
    if max_chars > 0 and rendered != "none" and len(rendered) > max_chars:
        rendered, _ = _truncate_text(rendered, max_chars)

    return rendered, {
        **allowed_metrics,
        **required_contracts_metrics,
        **required_members_metrics,
        **model_surfaces_metrics,
        **same_class_methods_metrics,
        **reuse_existing_logic_metrics,
        "visible_implementation_facts_chars": len(rendered) if rendered != "none" else 0,
        "visible_implementation_facts_original_chars": original_chars,
        "visible_return_types": sorted(fields_by_type),
    }


def _required_project_imports_from_symbols(
    project_context: dict[str, Any],
    symbols: list[str],
) -> list[str]:
    """Render imports for concrete visible symbols without test-specific rewrites.

    This helper is used by production generation/repair prompt assembly. It should
    not reinterpret class methods as parent-class imports or infer broader test
    setup needs; those rules belong to the generated-test prompt path only.
    """
    symbol_names = {
        str(symbol or "").strip().rsplit(".", 1)[-1]
        for symbol in symbols
        if str(symbol or "").strip()
    }
    if not symbol_names:
        return []

    imports: dict[str, set[str]] = {}

    def add_import_for_item(item: dict[str, Any]) -> None:
        name = str(item.get("name") or item.get("qualname", "").rsplit(".", 1)[-1]).strip()
        qualname = str(item.get("qualname") or "").strip()
        module_name = str(item.get("module_name") or "").strip()
        if not module_name and "." in qualname:
            module_name = qualname.rsplit(".", 1)[0]
        if name in symbol_names and module_name:
            imports.setdefault(module_name, set()).add(name)

    for item in _contract_symbols_from_project_context(project_context):
        if isinstance(item, dict):
            add_import_for_item(item)

    for item in project_context.get("required_contracts") or []:
        if isinstance(item, dict):
            add_import_for_item(item)

    for item in project_context.get("model_surfaces") or []:
        if isinstance(item, dict):
            add_import_for_item(item)

    return [
        f"from {module_name} import {', '.join(sorted(imports[module_name]))}"
        for module_name in sorted(imports)
    ]


def _required_project_imports_from_symbols_for_tests(
    project_context: dict[str, Any],
    symbols: list[str],
) -> list[str]:
    """Render imports for generated tests.

    Tests may need to import a parent class when the test plan references one of
    its methods, but they must still avoid importing class methods as top-level
    functions. Keeping this logic separate prevents test-only import inference
    from changing production generation or repair prompts.
    """
    symbol_values = [str(symbol or "").strip() for symbol in symbols if str(symbol or "").strip()]
    symbol_names = {symbol.rsplit(".", 1)[-1] for symbol in symbol_values}

    for symbol in symbol_values:
        parts = symbol.split(".")
        if len(parts) >= 2 and parts[-2][:1].isupper():
            symbol_names.add(parts[-2])

    if not symbol_names:
        return []

    imports: dict[str, set[str]] = {}

    def add_symbol_import(module_name: str, name: str) -> None:
        module_name = str(module_name or "").strip()
        name = str(name or "").strip()
        if module_name and name:
            imports.setdefault(module_name, set()).add(name)

    def add_import_for_item(item: dict[str, Any]) -> None:
        name = str(item.get("name") or item.get("qualname", "").rsplit(".", 1)[-1]).strip()
        qualname = str(item.get("qualname") or "").strip()
        kind = str(item.get("kind") or "").strip().lower()
        module_name = str(item.get("module_name") or "").strip()
        parent_qualname = str(item.get("parent_qualname") or item.get("parent") or "").strip()

        if kind == "method":
            if name not in symbol_names and qualname not in symbol_values:
                return
            parent = parent_qualname
            if not parent and qualname.count(".") >= 2:
                parent = qualname.rsplit(".", 1)[0]
            if parent and parent.rsplit(".", 1)[-1][:1].isupper():
                parent_module = parent.rsplit(".", 1)[0]
                parent_name = parent.rsplit(".", 1)[-1]
                add_symbol_import(parent_module, parent_name)
            return

        if not module_name and "." in qualname:
            module_name = qualname.rsplit(".", 1)[0]
        if name in symbol_names and module_name:
            add_symbol_import(module_name, name)

    for item in _contract_symbols_from_project_context(project_context):
        if isinstance(item, dict):
            add_import_for_item(item)

    for item in project_context.get("model_surfaces") or []:
        if isinstance(item, dict):
            add_import_for_item(item)

    return [
        f"from {module_name} import {', '.join(sorted(imports[module_name]))}"
        for module_name in sorted(imports)
    ]


def _required_project_imports_for_codegen(
    project_context: dict[str, Any],
    change_request: dict[str, Any] | None,
) -> str:
    request_parts = [
        str((change_request or {}).get("title") or ""),
        str((change_request or {}).get("description") or ""),
        *[str(item or "") for item in ((change_request or {}).get("constraints") or [])],
        *[str(item or "") for item in ((change_request or {}).get("notes") or [])],
    ]
    request_text = "\n".join(request_parts).lower()

    symbols: list[str] = []
    for item in project_context.get("required_contracts") or []:
        qualname = str(item.get("qualname") or "").strip()
        if qualname:
            symbols.append(qualname)


    for item in project_context.get("model_surfaces") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("qualname", "").rsplit(".", 1)[-1]).strip()
        qualname = str(item.get("qualname") or "").strip()
        if name and qualname and name.lower() in request_text:
            symbols.append(qualname)

    imports = _required_project_imports_from_symbols(project_context, symbols)
    return "\n".join(imports)




def _required_project_imports_for_tests(
    project_context: dict[str, Any],
    change_request: dict[str, Any] | None,
) -> str:
    """Render project imports for generated-test prompts only.

    This keeps test setup hints from affecting production generate/repair prompts.
    It may include required reuse contracts from contract_context because tests often
    need to import helper functions referenced by the generated target code.
    """
    request_parts = [
        str((change_request or {}).get("title") or ""),
        str((change_request or {}).get("description") or ""),
        *[str(item or "") for item in ((change_request or {}).get("constraints") or [])],
        *[str(item or "") for item in ((change_request or {}).get("notes") or [])],
    ]
    request_text = "\n".join(request_parts).lower()

    symbols: list[str] = []
    for item in project_context.get("required_contracts") or []:
        qualname = str(item.get("qualname") or "").strip()
        if qualname:
            symbols.append(qualname)

    for item in (project_context.get("contract_context") or {}).get("related_symbols") or []:
        if not isinstance(item, dict):
            continue
        qualname = str(item.get("qualname") or "").strip()
        name = qualname.rsplit(".", 1)[-1]
        role = str(item.get("role") or "").lower()
        if qualname and ("required" in role or (name and name.lower() in request_text)):
            symbols.append(qualname)

    for item in project_context.get("model_surfaces") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("qualname", "").rsplit(".", 1)[-1]).strip()
        qualname = str(item.get("qualname") or "").strip()
        if name and qualname and name.lower() in request_text:
            symbols.append(qualname)

    imports = _required_project_imports_from_symbols_for_tests(project_context, symbols)
    return "\n".join(imports)


_DOCSTRING_START_RE = re.compile(r"^[ \t]*(?:[rRuUbB]{0,3})?(\"\"\"|\'\'\')")
_HEADER_START_RE = re.compile(r"^[ \t]*(?:async[ \t]+def|def|class)[ \t]+.*:[ \t]*(?:#.*)?$")


def _line_indent_width(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def _docstring_quote_at_line_start(line: str) -> str | None:
    match = _DOCSTRING_START_RE.match(line)
    return str(match.group(1)) if match else None


def _skip_docstring_block(lines: list[str], start_index: int, quote: str) -> int:
    """Return the first line index after a standalone docstring block."""
    line = lines[start_index]
    # A one-line docstring contains both the opening and the closing triple
    # quote on the same line. Count occurrences instead of looking only at the
    # suffix because docstrings can have a prefix like r"""...""".
    if line.count(quote) >= 2:
        return start_index + 1

    index = start_index + 1
    while index < len(lines):
        if quote in lines[index]:
            return index + 1
        index += 1
    return index


def _strip_docstrings_from_python_source_by_lines(source: str) -> tuple[str, bool]:
    """Best-effort docstring removal for incomplete source excerpts.

    Some project-context snippets are not complete Python modules, so AST parsing
    can fail. For generated-test prompts we still want to remove examples from
    module/class/function docstrings while leaving executable code untouched.
    """
    raw = str(source or "")
    if not raw.strip():
        return raw, False

    lines = raw.splitlines()
    kept: list[str] = []
    changed = False
    module_docstring_allowed = True
    pending_header_indent: int | None = None
    index = 0

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        significant = bool(stripped) and not stripped.startswith("#")

        if not significant:
            kept.append(line)
            index += 1
            continue

        indent = _line_indent_width(line)
        quote = _docstring_quote_at_line_start(line)
        header_docstring_allowed = (
            pending_header_indent is not None and indent > pending_header_indent
        )

        if quote and (module_docstring_allowed or header_docstring_allowed):
            index = _skip_docstring_block(lines, index, quote)
            changed = True
            module_docstring_allowed = False
            pending_header_indent = None
            continue

        module_docstring_allowed = False
        if pending_header_indent is not None and indent <= pending_header_indent:
            pending_header_indent = None

        if _HEADER_START_RE.match(line):
            pending_header_indent = indent

        kept.append(line)
        index += 1

    if not changed:
        return raw, False

    # Preserve the original trailing newline convention when possible.
    rendered = "\n".join(kept)
    if raw.endswith("\n"):
        rendered += "\n"
    return rendered, True


def _strip_docstrings_from_python_source(source: str) -> tuple[str, bool]:
    """Return Python source without module/class/function docstrings.

    The helper is used only for generated-test prompt rendering. It does not
    change generated artifacts or project source files. If a snippet cannot be
    parsed as a complete Python module, a conservative line-based fallback is
    used for source excerpts.
    """
    raw = str(source or "")
    if not raw.strip():
        return raw, False

    try:
        tree = ast.parse(textwrap.dedent(raw))
    except SyntaxError:
        return _strip_docstrings_from_python_source_by_lines(raw)

    changed = False

    def remove_docstring(body: list[ast.stmt]) -> None:
        nonlocal changed
        if not body:
            return
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            del body[0]
            changed = True

    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            remove_docstring(node.body)

    if not changed:
        return _strip_docstrings_from_python_source_by_lines(raw)

    try:
        return ast.unparse(tree).strip(), True
    except Exception:
        logger.debug("failed to unparse source without docstrings", exc_info=True)
        return _strip_docstrings_from_python_source_by_lines(raw)


def _required_repair_import_changes_text(
    required_imports_text: str,
    error_context: dict[str, Any],
) -> str:
    unknown_names: set[str] = set()
    summary = error_context.get("verification_summary") or {}
    for block in summary.get("failed_blocks") or []:
        for issue in block.get("issues") or []:
            code = str(issue.get("code") or "")
            if code not in {"unknown_runtime_name", "unknown_annotation_name"}:
                continue
            for name in issue.get("unknown_names") or []:
                if str(name or "").strip():
                    unknown_names.add(str(name).strip())
            message = str(issue.get("message") or "")
            for token in re.findall(r"`([A-Za-z_]\w*)`", message):
                unknown_names.add(token)

    if not unknown_names:
        return ""

    entries: list[dict[str, Any]] = []
    for raw_line in required_imports_text.splitlines():
        line = raw_line.strip()
        match = re.match(r"from\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s+import\s+(.+)$", line)
        if not match:
            continue
        module = match.group(1)
        names = [name.strip() for name in match.group(2).split(",") if name.strip()]
        selected = [name for name in names if name in unknown_names]
        if selected:
            entries.append({"action": "add_from_import", "module": module, "names": selected})

    return _pretty(entries) if entries else ""



def _available_names_from_import_context(import_context_text: str) -> set[str]:
    names: set[str] = set()
    for raw_line in str(import_context_text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        from_match = re.match(r"from\s+[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*\s+import\s+(.+)$", line)
        if from_match:
            for part in from_match.group(1).split(","):
                name_part = part.strip()
                if not name_part:
                    continue
                name = name_part.split(" as ", 1)[-1].strip() if " as " in name_part else name_part.split(" as ", 1)[0].strip()
                if name and name != "*":
                    names.add(name)
            continue
        import_match = re.match(r"import\s+(.+)$", line)
        if import_match:
            for part in import_match.group(1).split(","):
                module_part = part.strip()
                if not module_part:
                    continue
                if " as " in module_part:
                    names.add(module_part.split(" as ", 1)[-1].strip())
                else:
                    names.add(module_part.split(".", 1)[0].strip())
    return {name for name in names if name}


def _required_import_changes_from_import_lines(
    required_imports_text: str,
    *,
    existing_import_context: str = "",
    only_names: set[str] | None = None,
) -> str:
    existing_names = _available_names_from_import_context(existing_import_context)
    entries: list[dict[str, Any]] = []

    for raw_line in str(required_imports_text or "").splitlines():
        line = raw_line.strip()
        match = re.match(r"from\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s+import\s+(.+)$", line)
        if not match:
            continue
        module = match.group(1)
        names = [name.strip() for name in match.group(2).split(",") if name.strip()]
        selected: list[str] = []
        for name in names:
            public_name = name.split(" as ", 1)[-1].strip() if " as " in name else name
            raw_name = name.split(" as ", 1)[0].strip()
            if not raw_name or public_name in existing_names:
                continue
            if only_names is not None and public_name not in only_names and raw_name not in only_names:
                continue
            selected.append(name)
        if selected:
            entries.append({"action": "add_from_import", "module": module, "names": selected})

    return _pretty(entries) if entries else ""

def _block_limit(runtime_config: RuntimeConfig | None, group: str, key: str, default: int) -> int:
    if runtime_config is None:
        return default
    limits = getattr(runtime_config.prompt_assembly, group, None) or {}
    if isinstance(limits, dict):
        return int(limits.get(key, default) or default)
    return default

def _contract_symbols_from_project_context(project_context: dict[str, Any]) -> list[dict[str, Any]]:
    contract_context = project_context.get("contract_context") or {}
    related_symbols = contract_context.get("related_symbols") or project_context.get("related_symbols") or []
    return [dict(item) for item in related_symbols]


def _render_contract_context(
    project_context: dict[str, Any],
    max_items: int,
    per_item_chars: int,
    *,
    include_docstrings: bool = True,
    strip_source_docstrings: bool = False,
) -> tuple[str, dict[str, Any]]:
    symbols = _contract_symbols_from_project_context(project_context)[:max(0, max_items)]
    blocks: list[str] = []
    total_chars = 0
    qualnames: list[str] = []
    stripped_source_count = 0

    for item in symbols:
        source = str(item.get("source_excerpt", "") or "")
        if strip_source_docstrings and source:
            source, source_docstrings_removed = _strip_docstrings_from_python_source(source)
            if source_docstrings_removed:
                stripped_source_count += 1
        if per_item_chars > 0 and len(source) > per_item_chars:
            source, _ = _truncate_text(source, per_item_chars)
        qualname = str(item.get("qualname", "") or item.get("name", "") or "")
        file_path = str(item.get("file_path", "") or "")
        kind = str(item.get("kind", "") or "")
        role = str(item.get("role", "") or "")
        origin_qualname = str(item.get("origin_qualname", "") or "")
        relation_kind = str(item.get("relation_kind", "") or "")
        direction = str(item.get("relation_direction", "") or "")
        confidence = str(item.get("relation_confidence", "") or "")
        signature = str(item.get("signature", "") or "").strip()
        docstring = str(item.get("docstring", "") or "").strip().replace("\n", " ")

        lines = [
            f"Qualname: {qualname}",
            f"File: {file_path}",
            f"Kind: {kind}",
            f"Role: {role}",
            f"Origin: {origin_qualname}" if origin_qualname else "Origin: target",
            f"Relation: {direction}/{relation_kind}/{confidence}",
        ]
        if signature:
            lines.append(f"Signature: {signature}")
        if include_docstrings and docstring:
            lines.append(f"Docstring: {docstring[:180]}")
        if source:
            source_header = (
                "Executable source excerpt without documentation:"
                if strip_source_docstrings
                else "Source excerpt:"
            )
            lines.append(source_header)
            lines.append(source)
            total_chars += len(source)
        blocks.append("\n".join(lines))
        qualnames.append(qualname)

    model_surfaces_text, model_surfaces_metrics = _render_model_surfaces(project_context, max_chars=max(800, per_item_chars))
    if model_surfaces_text and model_surfaces_text != "none":
        blocks.append("Visible model surfaces (valid fields and constructor arguments):\n" + model_surfaces_text)

    rendered = "\n\n---\n\n".join(blocks) if blocks else "none"
    metrics = {
        "contract_symbols_count": len(blocks),
        "contract_symbol_chars": total_chars,
        "contract_symbol_qualnames": qualnames,
        "contract_symbol_sources_docstrings_removed": stripped_source_count,
        **model_surfaces_metrics,
    }
    return rendered, metrics




def _render_required_contracts(
    project_context: dict[str, Any],
    max_chars: int = 1000,
) -> tuple[str, dict[str, Any]]:
    contracts = project_context.get("required_contracts") or (
        (project_context.get("contract_context") or {}).get("required_contracts")
    ) or []
    compact: list[dict[str, Any]] = []
    for item in contracts:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        qualname = str(item.get("qualname") or "").strip()
        if not name and qualname:
            name = qualname.rsplit(".", 1)[-1]
        if not name:
            continue
        compact.append({
            "name": name,
            "qualname": qualname,
            "signature": str(item.get("signature") or ""),
            "reason": str(item.get("reason") or ""),
            "source": str(item.get("source") or ""),
        })
    if not compact:
        return "none", {"required_contracts_count": 0, "required_contracts_chars": 0}
    rendered = _pretty(compact)
    original_chars = len(rendered)
    if max_chars > 0 and len(rendered) > max_chars:
        rendered, _ = _truncate_text(rendered, max_chars)
    return rendered, {
        "required_contracts_count": len(compact),
        "required_contracts_chars": len(rendered),
        "required_contracts_original_chars": original_chars,
    }


def _render_required_class_members(
    project_context: dict[str, Any],
    max_chars: int = 1600,
) -> tuple[str, dict[str, Any]]:
    members = project_context.get("required_class_members") or (
        (project_context.get("contract_context") or {}).get("required_class_members")
    ) or []
    compact: list[dict[str, Any]] = []
    for item in members:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        compact.append({
            "name": name,
            "kind": str(item.get("kind") or "method"),
            "required": bool(item.get("required", True)),
            "sources": list(item.get("sources") or []),
            "exclusion_reason": str(item.get("exclusion_reason") or ""),
        })
    if not compact:
        return "none", {"required_class_members_count": 0, "required_class_members_chars": 0}
    rendered = _pretty(compact)
    original_chars = len(rendered)
    if max_chars > 0 and len(rendered) > max_chars:
        rendered, _ = _truncate_text(rendered, max_chars)
    return rendered, {
        "required_class_members_count": len(compact),
        "required_class_members_chars": len(rendered),
        "required_class_members_original_chars": original_chars,
    }


def _render_model_surfaces(
    project_context: dict[str, Any],
    max_chars: int = 1400,
) -> tuple[str, dict[str, Any]]:
    surfaces = project_context.get("model_surfaces") or (
        (project_context.get("contract_context") or {}).get("model_surfaces")
    ) or []
    compact: list[dict[str, Any]] = []
    for item in surfaces:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        qualname = str(item.get("qualname") or "").strip()
        fields = [str(value) for value in (item.get("fields") or item.get("model_fields") or []) if str(value)]
        constructor_fields = [str(value) for value in (item.get("constructor_fields") or []) if str(value)]
        if not name and qualname:
            name = qualname.rsplit(".", 1)[-1]
        if not name or (not fields and not constructor_fields):
            continue
        compact.append({
            "name": name,
            "qualname": qualname,
            "fields": sorted(set(fields) | set(constructor_fields)),
            "constructor_fields": constructor_fields,
            "required_constructor_fields": list(item.get("required_constructor_fields") or []),
            "source": str(item.get("source") or ""),
        })
    if not compact:
        return "none", {"model_surfaces_count": 0, "model_surfaces_chars": 0}

    def surface_priority(item: dict[str, Any]) -> tuple[int, str]:
        name_lower = str(item.get("name") or "").lower()
        role_names = ("result", "response", "dto", "schema", "view", "output")
        return (0 if any(role in name_lower for role in role_names) else 1, name_lower)

    compact = sorted(compact, key=surface_priority)
    rendered = _pretty(compact)
    original_chars = len(rendered)
    if max_chars > 0 and len(rendered) > max_chars:
        rendered, _ = _truncate_text(rendered, max_chars)
    return rendered, {
        "model_surfaces_count": len(compact),
        "model_surfaces_chars": len(rendered),
        "model_surfaces_original_chars": original_chars,
    }


def _render_contract_attribute_requirements(
    project_context: dict[str, Any],
    max_chars: int = 1600,
) -> tuple[str, dict[str, Any]]:
    requirements = project_context.get("contract_attribute_requirements") or (
        (project_context.get("contract_context") or {}).get("contract_attribute_requirements")
    ) or []
    compact: list[dict[str, Any]] = []
    for item in requirements:
        if not isinstance(item, dict):
            continue
        required_fields = [str(value) for value in (item.get("required_fields") or []) if str(value)]
        if not required_fields:
            continue
        compact.append(
            {
                "contract_qualname": item.get("contract_qualname", ""),
                "parameter": item.get("parameter", ""),
                "item_type": item.get("item_type", ""),
                "item_qualname": item.get("item_qualname", ""),
                "required_fields": required_fields,
                "model_fields": list(item.get("model_fields") or []),
                "constructor_fields": list(item.get("constructor_fields") or []),
                "required_constructor_fields": list(item.get("required_constructor_fields") or []),
                "source": item.get("source", ""),
            }
        )

    if not compact:
        return "", {
            "contract_attribute_requirements_count": 0,
            "contract_attribute_requirements_chars": 0,
            "contract_attribute_requirements_original_chars": 0,
        }

    rendered = _pretty(compact)
    original_chars = len(rendered)
    if max_chars > 0 and len(rendered) > max_chars:
        rendered, _ = _truncate_text(rendered, max_chars)
    return rendered, {
        "contract_attribute_requirements_count": len(compact),
        "contract_attribute_requirements_chars": len(rendered),
        "contract_attribute_requirements_original_chars": original_chars,
    }
def _build_coder_prompt_metrics(
    prompt: str,
    target_text: str,
    module_outline_text: str,
    full_file_text: str,
    reference_text: str,
    related_tests_text: str,
    contract_context_text: str,
    before_trim: int,
    after_trim: int,
    trim_steps: list[str] | None = None,
) -> dict[str, Any]:
    normalized_module_outline = _normalize_optional_value(module_outline_text)
    normalized_full_file = _normalize_optional_value(full_file_text)
    normalized_reference = _normalize_optional_value(reference_text)
    normalized_related_tests = _normalize_optional_value(related_tests_text)
    normalized_contract_context = _normalize_optional_value(contract_context_text)

    return {
        "coder_prompt_chars_before_trim": before_trim,
        "coder_prompt_chars_after_trim": after_trim,
        "coder_target_chars": len(target_text),
        "coder_module_outline_chars": len(normalized_module_outline),
        "coder_full_file_chars": len(normalized_full_file),
        "coder_reference_chars": len(normalized_reference),
        "coder_related_test_chars": len(normalized_related_tests),
        "coder_contract_context_chars": len(normalized_contract_context),
        "coder_trim_steps": list(trim_steps or []),
    }



_REQUEST_OUTPUT_MARKERS = (
    "долж", "обязан", "обязател", "вернуть", "возвращ", "return",
    "результат", "заканчив", "начин", "содерж", "формат", "расширен",
    "имя", "строк", "literal", "литерал", "точно",
)


_PRESERVE_EXISTING_MARKERS = (
    "сохран", "не менять", "без изменения", "остав", "текущ", "существующ",
    "структур", "формат", "публичн", "контракт", "кроме",
)


def _request_asks_to_preserve_existing_behavior_for_change_request(change_request: dict[str, Any] | None) -> bool:
    change_request = change_request or {}
    parts = [
        str(change_request.get("title", "") or ""),
        str(change_request.get("description", "") or ""),
        *[str(item) for item in (change_request.get("constraints") or []) if item],
    ]
    text = "\n".join(parts).lower()
    return any(marker in text for marker in _PRESERVE_EXISTING_MARKERS)

_LITERAL_TOKEN_RE = re.compile(
    r"`([^`]+)`|\"([^\"]+)\"|'([^']+)'|(?<![\w/])\.[A-Za-z0-9][A-Za-z0-9_.-]{0,30}(?![\w/])|\b[A-Za-z_][A-Za-z0-9_]*_[A-Za-z0-9_]*\b|\b[A-Z][A-Za-z0-9_]{2,}\b|\b[YMDAHhmsS_-]{4,}\b"
)


def _split_request_sentences(text: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    if not cleaned:
        return []
    parts = re.split(r"(?<=[.!?。])\s+|\n+|(?<=;)\s+", cleaned)
    return [part.strip(" -\t") for part in parts if part.strip(" -\t")]


def _extract_literal_tokens_from_text(text: str) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for match in _LITERAL_TOKEN_RE.finditer(str(text or "")):
        value = next((group for group in match.groups() if group), None) or match.group(0)
        value = str(value).strip()
        if not value or len(value) > 80:
            continue
        # Avoid treating common English/Russian words as literals. Keep snake_case,
        # dotted extensions, quoted/backtick text, CamelCase/API-like names and compact format tokens.
        if re.fullmatch(r"[A-Za-z]+", value) and "_" not in value and not re.search(r"[A-Z].*[A-Z]", value):
            continue
        if value not in seen:
            seen.add(value)
            tokens.append(value)
    return tokens[:16]


def _render_request_output_obligations(change_request: dict[str, Any]) -> str:
    """Render compact, request-derived output/literal obligations.

    This is intentionally generic: it does not know about specific examples like
    file extensions. It only extracts statements and literals that are explicitly
    present in the user's request, so old docstrings and related context cannot silently
    override them in code or generated tests.
    """
    title = str(change_request.get("title", "") or "")
    description = str(change_request.get("description", "") or "")
    constraints = [str(item) for item in (change_request.get("constraints") or []) if item]
    source_parts = [title, description, *constraints]
    source_text = "\n".join(part for part in source_parts if part).strip()
    if not source_text:
        return ""

    obligation_statements: list[str] = []
    seen_statements: set[str] = set()
    for sentence in _split_request_sentences(description):
        lower = sentence.lower()
        if any(marker in lower for marker in _REQUEST_OUTPUT_MARKERS):
            if sentence not in seen_statements:
                seen_statements.add(sentence)
                obligation_statements.append(sentence)
    for constraint in constraints:
        lower = constraint.lower()
        if any(marker in lower for marker in _REQUEST_OUTPUT_MARKERS):
            if constraint not in seen_statements:
                seen_statements.add(constraint)
                obligation_statements.append(constraint)

    literals = _extract_literal_tokens_from_text(source_text)

    if not obligation_statements and not literals:
        return ""

    lines = [
        "Явные требования запроса к результату и литералам:",
        "Эти требования извлечены только из пользовательского запроса. Если они противоречат старому описанию, исходному коду или связанным тестам, приоритет имеет пользовательский запрос.",
    ]
    if obligation_statements:
        lines.append("Требования к наблюдаемому результату или формату:")
        lines.extend(f"- {item}" for item in obligation_statements[:8])
    if literals:
        lines.append("Имена, литералы и форматы, которые нужно сохранить в поведении и тестах:")
        lines.extend(f"- {item}" for item in literals[:12])
    return "\n".join(lines)



_PRESERVE_EXISTING_MARKERS = (
    "сохран", "не менять", "без изменения", "остав", "текущ", "существующ",
    "структур", "формат", "публичн", "контракт", "кроме",
)


def _request_asks_to_preserve_existing_behavior(change_request: dict[str, Any]) -> bool:
    parts = [
        str(change_request.get("title", "") or ""),
        str(change_request.get("description", "") or ""),
        *[str(item) for item in (change_request.get("constraints") or []) if item],
    ]
    text = "\n".join(parts).lower()
    return any(marker in text for marker in _PRESERVE_EXISTING_MARKERS)


def _safe_unparse(node: ast.AST, max_chars: int = 120) -> str:
    try:
        text = ast.unparse(node).strip()
    except Exception:
        return ""
    text = re.sub(r"\s+", " ", text)
    if len(text) > max_chars:
        return text[: max_chars - 1].rstrip() + "…"
    return text


def _append_unique_limited(items: list[str], value: str, limit: int) -> None:
    value = str(value or "").strip()
    if value and value not in items and len(items) < limit:
        items.append(value)




def _statement_primary_action(stmt: ast.stmt) -> str:
    """Return a compact, generic description of one top-level action."""
    if isinstance(stmt, ast.If):
        condition = _safe_unparse(stmt.test, 110)
        nested_actions: list[str] = []
        for child in stmt.body[:3]:
            action = _statement_primary_action(child)
            if action:
                nested_actions.append(action)
        suffix = f" -> {'; '.join(nested_actions)}" if nested_actions else ""
        return f"if {condition}:{suffix}" if condition else ""
    if isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        return _safe_unparse(stmt, 160)
    if isinstance(stmt, ast.Expr):
        return _safe_unparse(stmt.value, 140)
    if isinstance(stmt, ast.With):
        items = ", ".join(_safe_unparse(item.context_expr, 90) for item in stmt.items)
        items = re.sub(r"\s+", " ", items).strip()
        nested_actions = []
        for child in stmt.body[:2]:
            action = _statement_primary_action(child)
            if action:
                nested_actions.append(action)
        suffix = f" -> {'; '.join(nested_actions)}" if nested_actions else ""
        return f"with {items}:{suffix}" if items else ""
    if isinstance(stmt, ast.Return):
        value = _safe_unparse(stmt.value, 120) if stmt.value is not None else ""
        return f"return {value}".strip()
    if isinstance(stmt, ast.Try):
        nested_actions = []
        for child in stmt.body[:2]:
            action = _statement_primary_action(child)
            if action:
                nested_actions.append(action)
        suffix = f": {'; '.join(nested_actions)}" if nested_actions else ""
        return f"try{suffix}"
    return ""


def _ordered_actions_from_tree(tree: ast.AST, limit: int = 14) -> list[str]:
    """Extract top-level action order from a function/class/module source tree."""
    body: list[ast.stmt] = []
    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = list(getattr(node, "body", []))
            break
    if not body:
        body = list(getattr(tree, "body", []))

    actions: list[str] = []
    for stmt in body:
        # Docstrings are not behavior-order anchors.
        if (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
        ):
            continue
        action = _statement_primary_action(stmt)
        if action:
            _append_unique_limited(actions, action, limit)
    return actions

def _render_replace_symbol_preservation_guidance(
    *,
    operation: str,
    change_request: dict[str, Any],
    target_source: str,
    max_chars: int = 1600,
) -> str:
    """Render compact source-derived anchors for cautious replace_symbol edits.

    The extraction is generic and does not contain project-specific names. Concrete
    names appear only when they are already present in the provided target source.
    """
    if str(operation or "").strip() != "replace_symbol":
        return ""
    if not _request_asks_to_preserve_existing_behavior(change_request):
        return ""

    source = textwrap.dedent(str(target_source or "")).strip()
    if not source or "# ... truncated" in source:
        # A truncated method is unsafe as a preservation source: rendered anchors
        # could be misleadingly incomplete. Template rules still require minimal edits.
        return (
            "Исходный target-код обрезан. Для замены symbol используй минимальное изменение: "
            "не переписывай реализацию с нуля и не меняй видимые вызовы, аргументы, "
            "формат данных и return-shape без явного требования пользователя."
        )

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ""

    ordered_actions = _ordered_actions_from_tree(tree)
    calls: list[str] = []
    assignments: list[str] = []
    conditions: list[str] = []
    dict_keys: list[str] = []
    returns: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            call_text = _safe_unparse(node, 140)
            if call_text:
                _append_unique_limited(calls, call_text, 10)
        elif isinstance(node, ast.Assign):
            assignment_text = _safe_unparse(node, 160)
            if assignment_text:
                _append_unique_limited(assignments, assignment_text, 10)
        elif isinstance(node, ast.AnnAssign):
            assignment_text = _safe_unparse(node, 160)
            if assignment_text:
                _append_unique_limited(assignments, assignment_text, 10)
        elif isinstance(node, ast.AugAssign):
            assignment_text = _safe_unparse(node, 160)
            if assignment_text:
                _append_unique_limited(assignments, assignment_text, 10)
        elif isinstance(node, ast.If):
            condition_text = _safe_unparse(node.test, 120)
            if condition_text:
                _append_unique_limited(conditions, condition_text, 8)
        elif isinstance(node, ast.Dict):
            for key in node.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    _append_unique_limited(dict_keys, key.value, 12)
        elif isinstance(node, ast.Return) and node.value is not None:
            return_text = _safe_unparse(node.value, 120)
            if return_text:
                _append_unique_limited(returns, return_text, 4)

    if not any((ordered_actions, calls, assignments, conditions, dict_keys, returns)):
        return ""

    lines: list[str] = [
        "Этот блок извлечен из текущей реализации. Если пользовательский запрос не требует обратного, сохрани эти элементы без замены альтернативной реализацией и меняй только необходимые строки.",
        "Сохраняй не только наличие перечисленных действий, но и их порядок. Новое действие вставляй в минимально подходящее место до первого использования значения, которое это действие обновляет.",
    ]
    if ordered_actions:
        lines.append("Порядок сохраняемых действий:")
        lines.extend(f"{idx}. {item}" for idx, item in enumerate(ordered_actions, start=1))
    if conditions:
        lines.append("Условия ветвления:")
        lines.extend(f"- {item}" for item in conditions)
    if assignments:
        lines.append("Присваивания и изменяемые значения:")
        lines.extend(f"- {item}" for item in assignments)
    if calls:
        lines.append("Видимые вызовы и их аргументы:")
        lines.extend(f"- {item}" for item in calls)
    if dict_keys:
        lines.append("Ключи явно создаваемых словарей:")
        lines.extend(f"- {item}" for item in dict_keys)
    if returns:
        lines.append("Форма возвращаемого значения:")
        lines.extend(f"- {item}" for item in returns)

    rendered = "\n".join(lines)
    if len(rendered) > max_chars:
        rendered, _ = _truncate_text(rendered, max_chars)
    return rendered


def _render_constraints_block(constraints: list[str], limit: int = 6) -> str:
    if not constraints:
        return "[]"
    return "\n".join(f"- {item}" for item in constraints[:limit])


def _compact_change_request_for_codegen(
    change_request: dict[str, Any],
    planner_result: dict[str, Any] | None = None,
    *,
    forbidden_existing_symbol_names: set[str] | None = None,
) -> str:
    title = str(change_request.get("title", "") or "").strip()
    description = str(change_request.get("description", "") or "").strip()
    constraints = [str(item) for item in (change_request.get("constraints") or []) if item]

    lines: list[str] = []
    if title:
        lines.append(f"Title: {title}")
    if description:
        description_short, _ = _truncate_text(description, 900)
        lines.append("Description:")
        lines.append(description_short)
    if constraints:
        critical_constraints = [
            item
            for item in constraints
            if any(
                marker in item.lower()
                for marker in (
                    "не ",
                    "только",
                    "видим",
                    "аргумент",
                    "keyword",
                    "constructor",
                    "словар",
                    "dict",
                )
            )
        ]
        if critical_constraints:
            lines.append("Critical request constraints:")
            lines.extend(f"- {item}" for item in critical_constraints[:8])
        lines.append("Request constraints:")
        lines.extend(f"- {item}" for item in constraints[:16])

    request_obligations = _render_request_output_obligations(change_request)
    if request_obligations:
        lines.append(request_obligations)

    if planner_result:
        filtered_planner = _filter_planner_result_for_insert_after(
            planner_result,
            user_text="\n".join(lines),
            forbidden_existing_symbol_names=forbidden_existing_symbol_names or set(),
        )
        explicit_requirements = [
            str(item).strip()
            for item in (filtered_planner.get("explicit_requirements") or [])
            if str(item).strip()
        ]
        preserve_literals = [
            str(item).strip()
            for item in (filtered_planner.get("preserve_literals") or [])
            if str(item).strip()
        ]
        intent_summary = str(filtered_planner.get("intent_summary", "") or "").strip()
        planner_constraints = [str(item) for item in (filtered_planner.get("constraints") or []) if item]

        if explicit_requirements:
            lines.append("Explicit user requirements from planner:")
            lines.extend(f"- {item}" for item in explicit_requirements[:10])
        if preserve_literals:
            lines.append("User-specified names, signatures and literals to preserve exactly:")
            lines.extend(f"- {item}" for item in preserve_literals[:12])
        if intent_summary:
            lines.append(f"Planned intent: {intent_summary}")
        if planner_constraints:
            lines.append("Planner constraints:")
            lines.extend(f"- {item}" for item in planner_constraints[:8])

    return "\n".join(lines).strip()


def _existing_symbol_names_from_project_context(pc: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for item in pc.get("module_outline") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("qualname", "").rsplit(".", 1)[-1]).strip()
        if name:
            names.add(name)
    for item in pc.get("class_members") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("qualname", "").rsplit(".", 1)[-1]).strip()
        if name:
            names.add(name)
    target = pc.get("target_symbol") or {}
    if isinstance(target, dict):
        source = str(target.get("source") or "")
        for match in re.finditer(r"^\s*(?:async\s+def|def|class)\s+([A-Za-z_]\w*)", source, flags=re.MULTILINE):
            names.add(match.group(1))
    return names


def _mentions_any_symbol(text: str, names: set[str]) -> bool:
    for name in names:
        if name and re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", text):
            return True
    return False


def _filter_planner_result_for_insert_after(
    planner_result: dict[str, Any],
    *,
    user_text: str,
    forbidden_existing_symbol_names: set[str],
) -> dict[str, Any]:
    if not forbidden_existing_symbol_names:
        result = dict(planner_result)
        result.pop("code", None)
        return result

    result = dict(planner_result)
    result.pop("code", None)
    user_text_lower = str(user_text or "").lower()

    def is_forbidden_item(item: object) -> bool:
        text = str(item or "").strip()
        if not text:
            return False
        for name in forbidden_existing_symbol_names:
            if not name:
                continue
            if not re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", text):
                continue
            if name.lower() not in user_text_lower:
                return True
        return False

    for key in ("explicit_requirements", "preserve_literals"):
        values = result.get(key) or []
        if isinstance(values, str):
            values = [values]
        result[key] = [str(item).strip() for item in values if str(item).strip() and not is_forbidden_item(item)]

    intent = str(result.get("intent_summary") or "").strip()
    if intent and is_forbidden_item(intent):
        result["intent_summary"] = "Создать новый symbol с уникальным именем по исходному запросу пользователя"
    return result


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
    target_executable_source, target_docstrings_removed = _strip_docstrings_from_python_source(target_source)

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

    # Keep the raw full-file source for compact structural guidance. The
    # rendered full-file block may be trimmed later, but constructor guidance
    # must remain based on the complete source when it is available.
    full_file_source_for_guidance = str(pc.get("full_file_source", "") or "").strip()
    full_file_source, full_file_docstrings_removed = _strip_docstrings_from_python_source(full_file_source_for_guidance)
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
        strip_source_docstrings=True,
    )
    if related_tests_text == "none":
        related_tests_text = ""

    reference_context_block, reference_metrics = _build_test_reference_context_block(
        request.reference_context or {},
        runtime_config=runtime_config,
    )
    contract_context_text, contract_metrics = _render_contract_context(
        pc,
        max_items=runtime_config.test_prompt_contract_symbols if runtime_config else 3,
        per_item_chars=runtime_config.test_prompt_contract_symbol_chars if runtime_config else 500,
        include_docstrings=False,
        strip_source_docstrings=True,
    )
    model_surfaces_text, model_surfaces_metrics = _render_model_surfaces(
        pc,
        max_chars=_block_limit(runtime_config, "generate_block_chars", "model_surfaces", 1200),
    )
    contract_metrics.update(model_surfaces_metrics)
    contract_context_block = _render_optional_block(
        "Связанные production-контракты",
        _normalize_optional_value(contract_context_text),
    )
    contract_attribute_text, contract_attribute_metrics = _render_contract_attribute_requirements(
        pc,
        max_chars=_block_limit(runtime_config, "generate_block_chars", "contract_attribute_requirements", 1600),
    )
    contract_attribute_block = _render_optional_block(
        "Contract attribute requirements for generated test data",
        _normalize_optional_value(contract_attribute_text),
    )
    required_imports_text = _required_project_imports_for_tests(pc, request.change_request)

    import_context_text = _extract_import_context(full_file_source)
    inferred_symbols = _infer_project_symbols(target_executable_source)
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

    source_priority_text = ""
    if target_source_origin == "generated_code_artifact":
        source_priority_text = (
            "Главный источник истины для теста — исполняемый код проверяемого метода без документации. "
            "Справочный контекст целевого файла и связанных методов используй только для импортов, сигнатур, стиля и окружающего кода. "
            "Документация, комментарии и примеры нужны только для общего понимания. "
            "Если пример из справочного контекста отличается от исполняемого кода, используй исполняемый код."
        )

    values = {
        "request": compact_request_text,
        "target_file": request.target.get("file_path", ""),
        "target_symbol": effective_target_symbol,
        "operation": request.target.get("operation", "replace_symbol"),
        "insert_scope": request.target.get("insert_scope") or "",
        "expected_new_symbol_kind": request.target.get("expected_new_symbol_kind") or "",
        "parent_qualname": request.target.get("parent_qualname") or "",
        "target_source": target_executable_source or "none",
        "full_file_source": full_file_source or "none",
        "related_tests_block": _render_optional_block("Связанные тесты проекта", related_tests_text),
        "import_context_block": _render_optional_block("Импорты из целевого файла", import_context_text),
        "inferred_symbols_block": _render_optional_block("Символы проекта из target-кода", inferred_symbols_text),
        "source_priority_block": _render_optional_block("Приоритет источников для теста", source_priority_text),
        "reference_context_block": reference_context_block,
        "contract_context_block": contract_context_block,
        "contract_attribute_requirements_block": contract_attribute_block,
        "required_imports_block": _render_optional_block("Required project imports", required_imports_text),
        "model_surfaces_block": _render_optional_block("Visible constructor and field contracts for test data", _normalize_optional_value(model_surfaces_text)),
        "test_behavior_guidance_block": _render_optional_block(
            "Target-derived test data strategy",
            _render_test_behavior_guidance(
                target_executable_source,
                target_file=str(request.target.get("file_path", "") or ""),
                full_file_source=full_file_source_for_guidance,
                contract_context_text=contract_context_text,
            ),
        ),
        "constructor_guidance_block": _render_optional_block(
            "Visible parent constructor contract for tests",
            _render_test_constructor_guidance(
                full_file_source=full_file_source_for_guidance,
                effective_target_symbol=effective_target_symbol,
                parent_qualname=str(request.target.get("parent_qualname") or ""),
                insert_scope=str(request.target.get("insert_scope") or ""),
                expected_new_symbol_kind=str(request.target.get("expected_new_symbol_kind") or ""),
            ),
        ),
        "anchor_symbol": anchor_symbol or "null",
    }

    logger.info(
        "build_test_planner_user_prompt template_vars=%s",
        sorted(values.keys()),
    )

    prompt = template_text.format(**values)
    if "{reference_context_block}" not in template_text and values.get("reference_context_block"):
        prompt += values["reference_context_block"]
    if "{required_imports_block}" not in template_text and values.get("required_imports_block"):
        prompt += values["required_imports_block"]
    if isinstance(available_user_chars, int) and available_user_chars > 0 and len(prompt) > available_user_chars and values.get("reference_context_block"):
        values["reference_context_block"] = ""
        prompt = template_text.format(**values)
    if isinstance(available_user_chars, int) and available_user_chars > 0 and len(prompt) > available_user_chars and values.get("contract_context_block"):
        values["contract_context_block"] = ""
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
        "test_planner_contract_symbols_count": int(contract_metrics.get("contract_symbols_count", 0) or 0),
        "test_planner_contract_symbol_chars": int(contract_metrics.get("contract_symbol_chars", 0) or 0),
        "test_planner_contract_attribute_requirements_count": int(contract_attribute_metrics.get("contract_attribute_requirements_count", 0) or 0),
        "test_planner_contract_attribute_requirements_chars": int(contract_attribute_metrics.get("contract_attribute_requirements_chars", 0) or 0),
        "test_planner_has_reference_context": bool(values.get("reference_context_block")),
        "test_planner_has_contract_context": bool(values.get("contract_context_block")),
        "test_planner_has_contract_attribute_requirements": bool(values.get("contract_attribute_requirements_block")),
    }
    return prompt, metrics

def build_planner_user_prompt(
    template_text: str,
    request: GenerationRequest,
    *,
    available_user_chars: int | None = None,
    default_constraints: list[str] | None = None,
    runtime_config: RuntimeConfig | None = None,
) -> tuple[str, dict[str, Any]]:
    pc = request.project_context or {}
    target_symbol = pc.get("target_symbol") or pc.get("target_function") or {}
    default_constraints = [str(item) for item in (default_constraints or []) if item]
    generate_limits = "generate_block_chars"

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
        per_item_chars=_block_limit(runtime_config, generate_limits, "related_tests", 700),
    )
    if related_tests_text == "none":
        related_tests_text = ""

    contract_limit = _block_limit(runtime_config, generate_limits, "contract_context", 3200)
    contract_items = max(1, int(getattr(runtime_config, "coder_max_contract_symbols", 4) if runtime_config else 4))
    contract_context_text, contract_metrics = _render_contract_context(
        pc,
        max_items=contract_items,
        per_item_chars=max(300, contract_limit // contract_items),
    )
    if contract_context_text == "none":
        contract_context_text = ""

    allowed_api_surface_text, allowed_surface_metrics = _render_allowed_api_surface(
        pc,
        max_chars=_block_limit(runtime_config, generate_limits, "allowed_api_surface", 2200),
    )
    if allowed_api_surface_text == "none":
        allowed_api_surface_text = ""

    visible_facts_text, visible_facts_metrics = _render_visible_implementation_facts(
        pc,
        max_chars=_block_limit(runtime_config, generate_limits, "allowed_api_surface", 2200),
    )
    if visible_facts_text == "none":
        visible_facts_text = ""

    reference_text, reference_metrics = _render_reference_artifacts(
        request.reference_context or {},
        max_items=1,
        per_item_chars=_block_limit(runtime_config, generate_limits, "reference", 700),
    )
    if reference_text == "none":
        reference_text = ""

    logger.info(
        "build_planner_user_prompt available_user_chars_type=%s default_constraints_count=%s",
        type(available_user_chars).__name__,
        len(default_constraints),
    )

    if isinstance(available_user_chars, int) and available_user_chars > 0:
        limits = {
            "module_outline": _block_limit(runtime_config, generate_limits, "module_outline", 1000),
            "target_source": _block_limit(runtime_config, generate_limits, "target_source", 1800),
            "full_file": _block_limit(runtime_config, generate_limits, "full_file", 2600),
            "related_tests": _block_limit(runtime_config, generate_limits, "related_tests", 700),
            "contract_context": contract_limit,
            "reference": _block_limit(runtime_config, generate_limits, "reference", 700),
        }
        if len(module_outline_text) > limits["module_outline"]:
            module_outline_text, _ = _truncate_text(module_outline_text, limits["module_outline"])
        if len(target_source) > limits["target_source"]:
            target_source, _ = _truncate_text(target_source, limits["target_source"])
        if len(full_file_source) > limits["full_file"]:
            full_file_source, _ = _truncate_text(full_file_source, limits["full_file"])
        if len(related_tests_text) > limits["related_tests"]:
            related_tests_text, _ = _truncate_text(related_tests_text, limits["related_tests"])
        if len(contract_context_text) > limits["contract_context"]:
            contract_context_text, _ = _truncate_text(contract_context_text, limits["contract_context"])
        if len(reference_text) > limits["reference"]:
            reference_text, _ = _truncate_text(reference_text, limits["reference"])

    values = {
        "request": compact_request_text,
        "target_file": request.target.get("file_path", ""),
        "target_symbol": request.target.get("qualname", ""),
        "operation": request.target.get("operation", "replace_symbol"),
        "insert_scope": request.target.get("insert_scope") or "module_body",
        "expected_new_symbol_kind": request.target.get("expected_new_symbol_kind") or "",
        "parent_qualname": request.target.get("parent_qualname") or "",
        "insert_after": request.target.get("insert_after") or request.target.get("qualname", "") or "null",
        "reference_symbol": "null",
        "module_outline_block": _render_optional_block("Структура модуля", module_outline_text),
        "target_function_block": _render_optional_block("Целевой symbol / anchor", target_source),
        "full_file_source_block": _render_optional_block("Полный исходный текст файла", full_file_source),
        "related_tests_block": _render_optional_block("Связанные тесты проекта", related_tests_text),
        "allowed_api_surface_block": _render_optional_block("Allowed API Surface", allowed_api_surface_text),
        "visible_implementation_facts_block": _render_optional_block("Visible implementation facts", visible_facts_text),
        "contract_context_block": _render_optional_block("Связанные production-контракты", contract_context_text),
        "reference_function_block": _render_optional_block("Reference artifacts", reference_text),
    }

    logger.info(
        "build_planner_user_prompt template_vars=%s",
        sorted(values.keys()),
    )

    prompt = template_text.format(**values)
    metrics = {
        "planner_prompt_chars": len(prompt),
        "planner_request_chars": len(compact_request_text),
        "planner_module_outline_chars": len(module_outline_text),
        "planner_target_chars": len(target_source),
        "planner_full_file_chars": len(full_file_source),
        "planner_related_tests_count": int(related_test_metrics.get("related_tests_count", 0) or 0),
        "planner_related_test_chars": int(related_test_metrics.get("related_test_chars", 0) or 0),
        "planner_contract_symbols_count": int(contract_metrics.get("contract_symbols_count", 0) or 0),
        "planner_contract_symbol_chars": int(contract_metrics.get("contract_symbol_chars", 0) or 0),
        "planner_allowed_api_surface_chars": int(allowed_surface_metrics.get("allowed_api_surface_chars", 0) or 0),
        "planner_visible_implementation_facts_chars": int(visible_facts_metrics.get("visible_implementation_facts_chars", 0) or 0),
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
    preserve_existing_mode = (
        requested_operation == "replace_symbol"
        and _request_asks_to_preserve_existing_behavior_for_change_request(request.change_request)
    )

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

    contract_context_text, contract_metrics = _render_contract_context(
        pc,
        max_items=runtime_config.coder_max_contract_symbols,
        per_item_chars=runtime_config.coder_max_contract_symbol_chars,
    )
    contract_context_text = _normalize_optional_value(contract_context_text)

    preservation_guidance_text = _render_replace_symbol_preservation_guidance(
        operation=requested_operation,
        change_request=request.change_request,
        target_source=target_text,
    )
    coder_visible_facts_text, coder_visible_facts_metrics = _render_visible_implementation_facts(
        pc,
        max_chars=getattr(runtime_config.prompt_assembly, "allowed_api_surface_chars", 1600),
    )
    coder_visible_facts_text = _normalize_optional_value(coder_visible_facts_text)
    required_imports_text = _required_project_imports_for_codegen(pc, request.change_request)
    available_imports_text = _render_available_imports(pc)
    available_import_lines = _available_import_lines_from_project_context(pc)
    full_file_import_context_text = _extract_import_context(full_file_text or str(pc.get("full_file_source", "") or ""))
    existing_import_context_text = "\n".join(
        part for part in [available_import_lines, full_file_import_context_text] if part
    )
    required_codegen_import_changes_text = _required_import_changes_from_import_lines(
        required_imports_text,
        existing_import_context=existing_import_context_text,
    )
    if required_codegen_import_changes_text:
        coder_visible_facts_text = (
            "Required import_changes for visible project symbols if these names are used directly in code:\n"
            f"{required_codegen_import_changes_text}\n\n"
            f"{coder_visible_facts_text}"
        )
    if required_imports_text:
        coder_visible_facts_text = (
            "Required project imports for visible project symbols:\n"
            f"{required_imports_text}\n\n"
            f"{coder_visible_facts_text}"
        )
    protected_contract_context = _render_optional_block(
        "Allowed API Surface and visible implementation facts (authoritative)",
        coder_visible_facts_text,
    )
    if protected_contract_context and contract_context_text:
        contract_context_text = f"{protected_contract_context}\n\n---\n\n{contract_context_text}"
    elif protected_contract_context:
        contract_context_text = protected_contract_context

    forbidden_existing_symbol_names = set()
    if requested_operation == "insert_after_symbol":
        forbidden_existing_symbol_names = _existing_symbol_names_from_project_context(pc)
    effective_planner_result = _filter_planner_result_for_insert_after(
        planner_result,
        user_text=_compact_change_request_for_codegen(request.change_request, None),
        forbidden_existing_symbol_names=forbidden_existing_symbol_names,
    )
    compact_request_text = _compact_change_request_for_codegen(
        request.change_request,
        effective_planner_result,
        forbidden_existing_symbol_names=forbidden_existing_symbol_names,
    )

    target_limit = int(runtime_config.coder_prompt_target_chars or 0)
    hard_limit = int(runtime_config.coder_prompt_hard_limit or 0)
    runtime_limit = int(available_user_chars or 0) if available_user_chars else 0

    # Это не жесткий лимит, а рабочая цель.
    # Даем небольшой люфт, потому что planner и coder могут слегка выходить за target.
    soft_limit = target_limit + 250 if target_limit > 0 else 0

    # Реальный предел, после которого уже надо агрессивно ужиматься.
    effective_limit = runtime_limit or hard_limit or soft_limit or 0
    if preserve_existing_mode:
        # Для replace_symbol-задач, где пользователь просит сохранить структуру/формат,
        # потеря контекста опаснее умеренного увеличения prompt-а. Держим локальный
        # минимум даже если старая конфигурация еще не обновлена.
        soft_limit = max(soft_limit, 38000) if soft_limit else 38000
        effective_limit = max(effective_limit, 38000) if effective_limit else 38000

    trim_steps: list[str] = []

    def _record(step: str) -> None:
        trim_steps.append(step)

    preservation_guidance_block = _render_optional_block(
        "Сохраняемые элементы текущей реализации",
        preservation_guidance_text,
    )

    planner_json_text = _pretty(effective_planner_result)

    def _section_sizes(
        *,
        stage: str,
        module_outline_value: str,
        target_value: str,
        full_file_value: str,
        reference_value: str,
        related_tests_value: str,
        contract_context_value: str,
        request_value: str,
    ) -> dict[str, int | str | bool]:
        return {
            "stage": stage,
            "preserve_existing_mode": preserve_existing_mode,
            "request": len(_normalize_optional_value(request_value)),
            "planner": len(planner_json_text),
            "target": len(_normalize_optional_value(target_value)),
            "module_outline": len(_normalize_optional_value(module_outline_value)),
            "full_file": len(_normalize_optional_value(full_file_value)),
            "related_tests": len(_normalize_optional_value(related_tests_value)),
            "reference": len(_normalize_optional_value(reference_value)),
            "contract_context": len(_normalize_optional_value(contract_context_value)),
            "preservation_guidance": len(_normalize_optional_value(preservation_guidance_text)),
            "available_imports": len(_normalize_optional_value(available_imports_text)),
            "required_import_changes": len(_normalize_optional_value(required_codegen_import_changes_text)),
        }

    def _render(
        module_outline_value: str,
        target_value: str,
        full_file_value: str,
        reference_value: str,
        related_tests_value: str,
        contract_context_value: str,
        request_value: str,
    ) -> str:
        return template_text.format(
            preservation_guidance_block=preservation_guidance_block,
            available_imports_block=_render_optional_block(
                "Доступные imports и имена целевого файла",
                available_imports_text,
            ),
            required_codegen_import_changes_block=_render_optional_block(
                "Required import_changes for names used by generated code",
                required_codegen_import_changes_text,
            ),
            operation=request.target.get("operation", "replace_symbol"),
            insert_scope=request.target.get("insert_scope") or "module_body",
            expected_new_symbol_kind=request.target.get("expected_new_symbol_kind") or "",
            parent_qualname=request.target.get("parent_qualname") or "",
            target_file=request.target.get("file_path", ""),
            target_symbol=request.target.get("qualname", ""),
            insert_after=request.target.get("insert_after")
            or request.target.get("qualname", "")
            or "null",
            reference_symbol="null",
            planner_json=planner_json_text,
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
            contract_context_block=_render_optional_block(
                "Связанные production-контракты",
                _normalize_optional_value(contract_context_value),
            ),
        )

    # Обязательные части
    current_module_outline = module_outline_text
    current_target = target_text
    current_request = compact_request_text

    # Опциональные части будем подключать по приоритету
    current_full_file = ""
    current_related_tests = ""
    # Keep Allowed API Surface / visible facts in the base prompt.
    # This context is authoritative and must not be skipped before full_file/reference.
    current_contract_context = contract_context_text
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
        current_contract_context,
        current_request,
    )
    before_trim = len(prompt)
    logger.info(
        "coder prompt section sizes request_id=%s stage=%s sizes=%s",
        request.request_id,
        "initial_base",
        _section_sizes(
            stage="initial_base",
            module_outline_value=current_module_outline,
            target_value=current_target,
            full_file_value=current_full_file,
            reference_value=current_reference,
            related_tests_value=current_related_tests,
            contract_context_value=current_contract_context,
            request_value=current_request,
        ),
    )

    # Если уже слишком длинно, сначала слегка ужимаем низкоприоритетные секции.
    # В preserve-mode не режем пользовательский запрос и target source: это
    # именно те данные, которые должны дойти до модели полностью.
    if soft_limit and len(prompt) > soft_limit and not preserve_existing_mode:
        current_request, _ = _truncate_text(current_request, 1400)
        _record("truncated request to 1400 in base prompt")
        prompt = _render(
            current_module_outline,
            current_target,
            current_full_file,
            current_reference,
            current_related_tests,
            current_contract_context,
            current_request,
        )

    if soft_limit and len(prompt) > soft_limit and current_target and not preserve_existing_mode:
        current_target, _ = _truncate_text(current_target, 500)
        _record("truncated target to 500 in base prompt")
        prompt = _render(
            current_module_outline,
            current_target,
            current_full_file,
            current_reference,
            current_related_tests,
            current_contract_context,
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
            current_contract_context,
            current_request,
        )

    # Теперь последовательно пытаемся добавить блоки по приоритету.
    for block_name, block_value in optional_blocks:
        block_text = _normalize_optional_value(block_value)
        if not block_text:
            continue

        prev_full_file = current_full_file
        prev_related_tests = current_related_tests
        prev_contract_context = current_contract_context
        prev_reference = current_reference
        prev_module_outline = current_module_outline

        if block_name == "full_file":
            current_full_file = block_text
        elif block_name == "related_tests":
            current_related_tests = block_text
        elif block_name == "contract_context":
            current_contract_context = block_text
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
            current_contract_context,
            current_request,
        )

        # Если вылезли слишком далеко за рабочую цель — откатываем этот блок.
        # Для preserve-mode ориентируемся на реальный лимит, а не на мягкую цель,
        # чтобы не выбрасывать full_file/related_tests слишком рано.
        optional_limit = effective_limit if preserve_existing_mode else soft_limit
        if optional_limit and len(candidate_prompt) > optional_limit:
            current_full_file = prev_full_file
            current_related_tests = prev_related_tests
            current_contract_context = prev_contract_context
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
            current_contract_context,
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
            current_contract_context,
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
            current_contract_context,
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
            current_contract_context,
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
            current_contract_context,
            current_request,
        )

    if effective_limit and len(prompt) > effective_limit and current_contract_context and not preserve_existing_mode:
        current_contract_context, _ = _truncate_text(current_contract_context, 900)
        _record("truncated protected contract_context to 900 on hard overflow")
        prompt = _render(
            current_module_outline,
            current_target,
            current_full_file,
            current_reference,
            current_related_tests,
            current_contract_context,
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
            current_contract_context,
            current_request,
        )

    if effective_limit and len(prompt) > effective_limit and current_request and not preserve_existing_mode:
        current_request, _ = _truncate_text(current_request, 1000)
        _record("truncated request to 1000 on hard overflow")
        prompt = _render(
            current_module_outline,
            current_target,
            current_full_file,
            current_reference,
            current_related_tests,
            current_contract_context,
            current_request,
        )

    if effective_limit and len(prompt) > effective_limit and current_target and not preserve_existing_mode:
        current_target, _ = _truncate_text(current_target, 160)
        _record("truncated target to 160 on hard overflow")
        prompt = _render(
            current_module_outline,
            current_target,
            current_full_file,
            current_reference,
            current_related_tests,
            current_contract_context,
            current_request,
        )

    final_section_sizes = _section_sizes(
        stage="final",
        module_outline_value=current_module_outline,
        target_value=current_target,
        full_file_value=current_full_file,
        reference_value=current_reference,
        related_tests_value=current_related_tests,
        contract_context_value=current_contract_context,
        request_value=current_request,
    )
    logger.info(
        "coder prompt section sizes request_id=%s stage=%s sizes=%s",
        request.request_id,
        "final",
        final_section_sizes,
    )
    if effective_limit and len(prompt) > effective_limit:
        logger.warning(
            "coder prompt remains over effective limit but protected sections were preserved request_id=%s operation=%s final_chars=%s effective_limit=%s preserve_existing_mode=%s section_sizes=%s",
            request.request_id,
            requested_operation,
            len(prompt),
            effective_limit,
            preserve_existing_mode,
            final_section_sizes,
        )

    metrics = _build_coder_prompt_metrics(
        prompt,
        current_target,
        current_module_outline,
        current_full_file,
        current_reference,
        current_related_tests,
        current_contract_context,
        before_trim,
        len(prompt),
        trim_steps,
    )
    metrics.update(ref_metrics)
    metrics.update(related_test_metrics)
    metrics.update(contract_metrics)
    metrics["coder_visible_implementation_facts_chars"] = int(
        coder_visible_facts_metrics.get("visible_implementation_facts_chars", 0) or 0
    )
    metrics["coder_available_imports_chars"] = len(available_imports_text)
    metrics["coder_preservation_guidance_chars"] = len(preservation_guidance_text)
    metrics["coder_prompt_section_sizes_final"] = final_section_sizes

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


def _build_repair_problem_block(
    error_context: dict[str, Any],
) -> str:
    verification_summary = (error_context or {}).get("verification_summary") or {}
    failed_blocks = verification_summary.get("failed_blocks") or []
    problems: list[dict[str, Any]] = []

    priority_by_code = {
        "unknown_model_constructor_keyword": 0,
        "model_constructor_field_type_mismatch": 1,
        "unknown_runtime_name": 2,
        "unknown_annotation_name": 3,
    }

    for block in failed_blocks:
        block_name = str(block.get("name") or "")
        details = block.get("details") or {}
        for issue in block.get("issues") or []:
            code = str(issue.get("code") or "")
            message = str(issue.get("message") or "")
            symbol = str(issue.get("symbol") or "")
            item: dict[str, Any] = {
                "block": block_name,
                "code": code,
                "message": message,
            }
            if symbol:
                item["symbol"] = symbol
            if code == "contract_call_uses_unrequested_literal_arg":
                item["repair_objective"] = (
                    "Do not keep or replace the failing argument with another placeholder literal. "
                    "Make the new symbol accept the required value as a parameter, reuse a local variable "
                    "from visible context, or choose another visible contract."
                )
            elif code == "unknown_injected_dependency_method":
                item["repair_objective"] = (
                    "Do not keep or rename the invented dependency method. Use only methods of injected "
                    "dependencies that are explicitly visible in target source, module/full file context, "
                    "related symbols, or contract context. If no such method exists, choose a visible contract "
                    "or make the required value an explicit parameter of the new symbol."
                )
            elif code in {"unknown_self_attribute", "unknown_self_method", "unknown_injected_dependency_attribute"}:
                self_details = details.get("self_attribute_usage_check") or {}
                injected_details = details.get("injected_dependency_method_check") or {}
                visible_attributes = self_details.get("known_attributes") or []
                visible_methods = self_details.get("known_methods") or []
                unknown_attributes = self_details.get("unknown_attributes") or []
                unknown_methods = self_details.get("unknown_methods") or []
                item["repair_objective"] = (
                    "Remove every use of the unknown self attribute or unknown self method from the repaired code. "
                    "Use only visible_attributes or visible_methods. If suggested_replacements are provided, "
                    "prefer them. Do not add a new alias, underscore field, or private helper call unless the "
                    "requested operation explicitly asks to add that new method."
                )
                item["visible_attributes"] = visible_attributes
                item["visible_methods"] = visible_methods
                item["unknown_attributes"] = unknown_attributes
                item["unknown_methods"] = unknown_methods
                if injected_details:
                    item["visible_dependency_types"] = injected_details.get("injected_attribute_types") or {}
                    item["known_methods_by_type"] = injected_details.get("known_methods_by_type") or {}
            elif code == "unknown_runtime_name":
                runtime_details = details.get("runtime_name_check") or {}
                item["repair_objective"] = (
                    "If the name is required, add the missing import through import_changes. "
                    "If an existing visible name can be used instead, replace the unknown name. "
                    "Do not leave unresolved names in repaired production code."
                )
                item["unknown_names"] = runtime_details.get("unknown_names") or []
            elif code == "unknown_model_constructor_keyword":
                item["repair_objective"] = (
                    "Keep the requested result/model object and fix the constructor call. "
                    "Replace invented or alias keyword arguments with only the visible constructor fields "
                    "listed in the diagnostic message. Do not replace the requested model/result object with dict."
                )
            elif code == "model_constructor_field_type_mismatch":
                model_details = details.get("model_surface_usage_check") or {}
                mismatches: list[dict[str, Any]] = []
                for checked_call in model_details.get("checked_constructor_calls") or []:
                    for mismatch in checked_call.get("field_type_mismatches") or []:
                        entry = dict(mismatch)
                        entry["class_name"] = checked_call.get("class_name")
                        mismatches.append(entry)
                item["repair_objective"] = (
                    "Before constructing the project model, convert serialized values to the visible field types. "
                    "Do not pass raw JSON/dict/file/service values into non-primitive model fields."
                )
                item["field_type_mismatches"] = mismatches[:5]
            problems.append(item)

    if not problems:
        return ""

    problems = sorted(
        problems,
        key=lambda item: (
            priority_by_code.get(str(item.get("code") or ""), 10),
            str(item.get("block") or ""),
            str(item.get("message") or ""),
        ),
    )

    return _render_optional_block(
        "Критическая ошибка для repair",
        _pretty({"issues": problems[:8]}),
    )

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

    target_source_for_guidance = _render_target_symbol(target_symbol)
    target_rendered = target_source_for_guidance
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
    contract_context_text, contract_metrics = _render_contract_context(
        project_context,
        max_items=runtime_config.repair_max_contract_symbols if runtime_config else 2,
        per_item_chars=runtime_config.repair_max_contract_symbol_chars if runtime_config else 500,
    )
    repair_model_surfaces_text, repair_model_surfaces_metrics = _render_model_surfaces(
        project_context,
        max_chars=_block_limit(runtime_config, "repair_block_chars", "model_surfaces", 900),
    )
    repair_model_surfaces_text = _normalize_optional_value(repair_model_surfaces_text)
    required_repair_imports_text = _required_project_imports_for_codegen(project_context, change_request)
    available_imports_text = _render_available_imports(project_context)
    available_import_lines = _available_import_lines_from_project_context(project_context)
    full_file_import_context_text = _extract_import_context(str(project_context.get("full_file_source", "") or ""))
    existing_import_context_text = "\n".join(
        part for part in [available_import_lines, full_file_import_context_text] if part
    )
    required_repair_import_changes = _required_repair_import_changes_text(
        required_repair_imports_text,
        request.error_context or {},
    )
    # Fall back to all required imports that are not already available in the target module.
    # This still only renders prompt data; it does not modify the artifact after the LLM response.
    if not required_repair_import_changes:
        required_repair_import_changes = _required_import_changes_from_import_lines(
            required_repair_imports_text,
            existing_import_context=existing_import_context_text,
        )
    required_repair_import_changes_block = _render_optional_block(
        "Required repair import_changes",
        required_repair_import_changes,
    )
    if required_repair_imports_text:
        contract_context_text = (
            "Required project imports for visible project symbols:\n"
            f"{required_repair_imports_text}\n\n---\n\n"
            f"{contract_context_text}"
        )
    if repair_model_surfaces_text and repair_model_surfaces_text != "none":
        contract_context_text = (
            "Visible model surfaces (valid fields and constructor arguments):\n"
            f"{repair_model_surfaces_text}\n\n---\n\n"
            f"{contract_context_text}"
        )
        contract_metrics.update(repair_model_surfaces_metrics)
    repair_preservation_guidance_text = _render_replace_symbol_preservation_guidance(
        operation=str(requested_operation or ""),
        change_request=change_request,
        target_source=target_source_for_guidance,
    )
    repair_preservation_guidance_block = _render_optional_block(
        "Сохраняемые элементы текущей реализации",
        repair_preservation_guidance_text,
    )
    contract_context_block = _render_optional_block(
        "Связанные production-контракты",
        _normalize_optional_value(contract_context_text),
    )
    contract_attribute_text, contract_attribute_metrics = _render_contract_attribute_requirements(
        project_context,
        max_chars=_block_limit(runtime_config, "generate_block_chars", "contract_attribute_requirements", 1600),
    )
    contract_attribute_requirements_block = _render_optional_block(
        "Contract attribute requirements",
        _normalize_optional_value(contract_attribute_text),
    )
    required_contracts_text, _required_contracts_metrics = _render_required_contracts(
        project_context,
        max_chars=_block_limit(runtime_config, "generate_block_chars", "required_contracts", 1000),
    )
    required_contracts_block = _render_optional_block(
        "Required production contract calls",
        _normalize_optional_value(required_contracts_text),
    )
    required_members_text, _required_members_metrics = _render_required_class_members(
        project_context,
        max_chars=_block_limit(runtime_config, "generate_block_chars", "required_class_members", 1000),
    )
    required_class_members_block = _render_optional_block(
        "Required class members",
        _normalize_optional_value(required_members_text),
    )
    syntax_error_block = _build_repair_syntax_error_block(
        request.error_context or {},
    )
    repair_problem_block = _build_repair_problem_block(
        request.error_context or {},
    )
    repair_scope_text = _repair_scope_from_error_context(request.error_context or {})
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
        "repair_problem_block": repair_problem_block,
        "repair_scope_block": _render_optional_block("Область repair", repair_scope_text),
        "preservation_guidance_block": repair_preservation_guidance_block,
        "available_imports_block": _render_optional_block(
            "Доступные imports и имена целевого файла",
            available_imports_text,
        ),
        "required_repair_import_changes_block": required_repair_import_changes_block,
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
        "contract_context_block": contract_context_block,
        "contract_attribute_requirements_block": contract_attribute_requirements_block,
        "required_contracts_block": required_contracts_block,
        "required_class_members_block": required_class_members_block,
    }

    prompt = template_text.format(**values)
    trim_steps: list[str] = []

    def _rerender() -> str:
        return template_text.format(**values)

    if hard_limit and len(prompt) > hard_limit and values["reference_context_block"]:
        values["reference_context_block"] = ""
        trim_steps.append("removed reference_context_block")
        prompt = _rerender()

    if hard_limit and len(prompt) > hard_limit and values["full_file_source_block"]:
        values["full_file_source_block"] = ""
        trim_steps.append("removed full_file_source_block")
        prompt = _rerender()

    if hard_limit and len(prompt) > hard_limit and values["module_outline_block"]:
        values["module_outline_block"] = ""
        trim_steps.append("removed module_outline_block")
        prompt = _rerender()

    if hard_limit and len(prompt) > hard_limit and values.get("required_class_members_block"):
        values["required_class_members_block"] = ""
        trim_steps.append("removed required_class_members_block")
        prompt = _rerender()

    if hard_limit and len(prompt) > hard_limit and values.get("required_contracts_block"):
        values["required_contracts_block"] = ""
        trim_steps.append("removed required_contracts_block")
        prompt = _rerender()

    if hard_limit and len(prompt) > hard_limit and values["contract_context_block"]:
        compact_contract, _ = _truncate_text(values["contract_context_block"], 1800)
        values["contract_context_block"] = compact_contract
        trim_steps.append("truncated contract_context_block to 1800")
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
        "has_previous_code=%s has_target=%s has_module_outline=%s has_full_file=%s has_contract_context=%s has_reference=%s",
        request.request_id,
        hard_limit,
        len(prompt),
        trim_steps,
        bool(values["previous_code_block"]),
        bool(values["target_function_block"]),
        bool(values["module_outline_block"]),
        bool(values["full_file_source_block"]),
        bool(values["contract_context_block"]),
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




def _available_import_lines_from_project_context(project_context: dict[str, Any]) -> str:
    items = project_context.get("available_imports") or []
    lines: list[str] = []
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source") or "").strip()
            if not source:
                kind = str(item.get("kind") or "").strip()
                module = str(item.get("module") or "").strip()
                imported = str(item.get("imported") or "").strip()
                asname = str(item.get("asname") or "").strip()
                if kind == "from_import" and module and imported:
                    source = f"from {module} import {imported}" + (f" as {asname}" if asname else "")
                elif kind == "import" and module:
                    source = f"import {module}" + (f" as {asname}" if asname else "")
            if source and source not in lines:
                lines.append(source)
    if lines:
        return "\n".join(lines)
    return _extract_import_context(str(project_context.get("full_file_source", "") or ""))


def _render_available_imports(project_context: dict[str, Any], *, max_items: int = 40) -> str:
    items = project_context.get("available_imports") or []
    if not isinstance(items, list) or not items:
        import_lines = _extract_import_context(str(project_context.get("full_file_source", "") or ""))
        if not import_lines:
            return ""
        return "\n".join(f"- {line}" for line in import_lines.splitlines()[:max_items])

    rendered: list[str] = []
    for item in items[:max_items]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        source = str(item.get("source") or "").strip()
        kind = str(item.get("kind") or "").strip()
        module = str(item.get("module") or "").strip()
        imported = str(item.get("imported") or "").strip()
        if not source:
            if kind == "from_import" and module and imported:
                source = f"from {module} import {imported}"
            elif kind == "import" and module:
                source = f"import {module}"
        if name and source:
            rendered.append(f"- {name}: {source}")
        elif source:
            rendered.append(f"- {source}")
    return "\n".join(rendered)


def _repair_scope_from_error_context(error_context: dict[str, Any]) -> str:
    summary = (error_context or {}).get("verification_summary") or {}
    codes: list[str] = []
    for block in summary.get("failed_blocks") or []:
        for issue in block.get("issues") or []:
            code = str(issue.get("code") or "").strip()
            if code:
                codes.append(code)
    if not codes:
        return ""
    import_only_codes = {
        "unknown_runtime_name",
        "unknown_annotation_name",
        "unresolved_import_change_module",
        "unresolved_import_change_name",
        "unused_import_change",
        "duplicated_import_change_with_local_import",
    }
    if all(code in import_only_codes for code in codes):
        return (
            "только imports\n"
            "Исправь import_changes, import-строки и минимально связанные обращения к импортируемому имени. "
            "Не переписывай остальное тело symbol."
        )
    return "code и imports"

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

    insert_scope = str(
        artifact_payload.get("insert_scope")
        or request.target.get("insert_scope")
        or ""
    ).strip()
    parent_qualname = str(
        artifact_payload.get("parent_qualname")
        or request.target.get("parent_qualname")
        or ""
    ).strip()
    if insert_scope == "class_body" and parent_qualname:
        return f"{parent_qualname}.{generated_symbol_name}", anchor_symbol or None

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
    *,
    strip_source_docstrings: bool = True,
) -> tuple[str, dict[str, Any]]:
    max_chars = int(runtime_config.test_prompt_reference_chars or 0) if runtime_config else 420
    max_items = runtime_config.prompt_assembly.test_reference_max_items if runtime_config else 1
    if max_chars <= 0 or max_items <= 0:
        return "", {"reference_count": 0, "reference_chars": 0}
    reference_text, metrics = _render_reference_artifacts(
        reference_context or {},
        max_items=max_items,
        per_item_chars=max_chars,
        strip_source_docstrings=strip_source_docstrings,
    )
    reference_text = _normalize_optional_value(reference_text)
    if not reference_text:
        return "", metrics
    return _render_optional_block("Справочные примеры для теста", reference_text), metrics






def _annotation_to_text(annotation: ast.AST | None) -> str:
    if annotation is None:
        return ""
    try:
        return ast.unparse(annotation)
    except Exception:
        if isinstance(annotation, ast.Name):
            return annotation.id
        if isinstance(annotation, ast.Attribute):
            parts = []
            node: ast.AST | None = annotation
            while isinstance(node, ast.Attribute):
                parts.append(node.attr)
                node = node.value
            if isinstance(node, ast.Name):
                parts.append(node.id)
            return ".".join(reversed(parts))
    return ""


def _parent_class_name_for_test_target(
    *,
    effective_target_symbol: str,
    parent_qualname: str,
    insert_scope: str,
    expected_new_symbol_kind: str,
) -> str:
    if parent_qualname:
        return parent_qualname.rsplit(".", 1)[-1]
    symbol = str(effective_target_symbol or "").strip()
    if insert_scope == "class_body" or expected_new_symbol_kind == "method":
        parts = symbol.split(".")
        if len(parts) >= 2:
            return parts[-2]
    return ""


def _class_init_contract_from_source(source: str, class_name: str) -> dict[str, Any]:
    if not source.strip() or not class_name:
        return {}
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}

    class_node = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and node.name == class_name
        ),
        None,
    )
    if class_node is None:
        return {}

    init_node = next(
        (
            child
            for child in class_node.body
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == "__init__"
        ),
        None,
    )
    if init_node is None:
        return {}

    positional_args = [*init_node.args.posonlyargs, *init_node.args.args]
    if positional_args and positional_args[0].arg == "self":
        positional_args = positional_args[1:]
    kwonly_args = list(init_node.args.kwonlyargs)
    params = [*positional_args, *kwonly_args]

    defaults_by_name: dict[str, ast.AST | None] = {}
    positional_defaults = list(init_node.args.defaults or [])
    if positional_defaults:
        default_start = max(0, len(positional_args) - len(positional_defaults))
        for arg, default in zip(positional_args[default_start:], positional_defaults):
            defaults_by_name[arg.arg] = default
    for arg, default in zip(kwonly_args, init_node.args.kw_defaults or []):
        defaults_by_name[arg.arg] = default

    rendered_params: list[str] = []
    required: list[str] = []
    annotations: dict[str, str] = {}
    for arg in params:
        annotation = _annotation_to_text(arg.annotation)
        if annotation:
            annotations[arg.arg] = annotation
        part = arg.arg + (f": {annotation}" if annotation else "")
        if arg.arg not in defaults_by_name:
            required.append(arg.arg)
        else:
            default = defaults_by_name.get(arg.arg)
            try:
                default_text = ast.unparse(default) if default is not None else "None"
            except Exception:
                default_text = "..."
            part += f" = {default_text}"
        rendered_params.append(part)

    return {
        "class_name": class_name,
        "signature": f"{class_name}({', '.join(rendered_params)})",
        "required": required,
        "annotations": annotations,
    }


def _render_test_constructor_guidance(
    *,
    full_file_source: str,
    effective_target_symbol: str,
    parent_qualname: str,
    insert_scope: str,
    expected_new_symbol_kind: str,
) -> str:
    class_name = _parent_class_name_for_test_target(
        effective_target_symbol=effective_target_symbol,
        parent_qualname=parent_qualname,
        insert_scope=insert_scope,
        expected_new_symbol_kind=expected_new_symbol_kind,
    )
    if not class_name:
        return ""

    contract = _class_init_contract_from_source(full_file_source, class_name)
    if not contract:
        return ""

    lines = [
        f"Видимый конструктор parent class для теста: {contract['signature']}.",
    ]
    required = list(contract.get("required") or [])
    if required:
        lines.append(
            "Обязательные аргументы конструктора нужно передать явно: "
            + ", ".join(required)
            + ". Не вызывай class без этих аргументов."
        )

    annotations = contract.get("annotations") or {}
    path_args = [
        name
        for name, annotation in annotations.items()
        if annotation.rsplit(".", 1)[-1] in {"Path", "PurePath"}
    ]
    if path_args:
        lines.append(
            "Для аргументов с типом Path/PurePath передавай объект pathlib.Path или pytest tmp_path, "
            "а не строку. Если используешь строковый literal, оберни его в Path(...), например Path('.')."
        )
        lines.append(
            "Если используешь Path(...), добавь `from pathlib import Path`; встроенная pytest fixture `tmp_path` допустима для Path-аргумента."
        )

    recommended_args: list[str] = []
    unsupported_required: list[str] = []
    for name in required:
        annotation = str(annotations.get(name, "") or "")
        annotation_tail = annotation.rsplit(".", 1)[-1]
        if annotation_tail in {"Path", "PurePath"}:
            recommended_args.append(f"{name}=tmp_path")
        elif annotation_tail in {"str", "String"}:
            recommended_args.append(f'{name}="test"')
        elif annotation_tail in {"int"}:
            recommended_args.append(f"{name}=1")
        elif annotation_tail in {"float"}:
            recommended_args.append(f"{name}=1.0")
        elif annotation_tail in {"bool"}:
            recommended_args.append(f"{name}=True")
        else:
            unsupported_required.append(name)

    if required and recommended_args and not unsupported_required:
        setup_line = f"target_obj = {class_name}(" + ", ".join(recommended_args) + ")"
        lines.append(
            "Рекомендуемый минимальный setup для parent instance: "
            f"`{setup_line}`. Скопируй этот шаблон вместо строковых заглушек или `__new__`."
        )
        if path_args:
            lines.append(
                "Если используешь recommended setup с `tmp_path`, добавь `tmp_path` как параметр pytest-тестовой функции."
            )
    elif required:
        lines.append(
            "Если не удается построить recommended setup для всех обязательных аргументов, "
            "не подставляй строковые или None-заглушки; используй fake/stub или явно показанный project-context пример."
        )

    return "\n".join(f"- {line}" for line in lines)


def _call_to_text(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def _dedupe_preserve_order(values: list[str], *, limit: int = 8) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _find_function_source_by_name(source: str, name: str) -> str:
    try:
        tree = ast.parse(textwrap.dedent(source or ""))
    except SyntaxError:
        return ""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            try:
                return ast.get_source_segment(textwrap.dedent(source or ""), node) or ast.unparse(node)
            except Exception:
                return ""
    return ""


def _extract_self_helper_calls(source: str) -> list[tuple[str, list[str]]]:
    calls: list[tuple[str, list[str]]] = []
    try:
        tree = ast.parse(textwrap.dedent(source or ""))
    except SyntaxError:
        return calls
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "self"):
            continue
        args = [_call_to_text(arg) for arg in node.args]
        args = [item for item in args if item]
        calls.append((func.attr, args))
    return calls


def _extract_attr_accesses_for_names(source: str, names: list[str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {name: [] for name in names if name}
    if not result:
        return result
    try:
        tree = ast.parse(textwrap.dedent(source or ""))
    except SyntaxError:
        return result

    def root_name(node: ast.AST) -> str:
        current = node
        while isinstance(current, ast.Attribute):
            current = current.value
        return current.id if isinstance(current, ast.Name) else ""

    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        root = root_name(node)
        if root not in result:
            continue
        text = _call_to_text(node)
        if text and text not in result[root]:
            result[root].append(text)
    return {key: values[:8] for key, values in result.items() if values}


def _extract_return_expressions(source: str) -> list[str]:
    returns: list[str] = []
    try:
        tree = ast.parse(textwrap.dedent(source or ""))
    except SyntaxError:
        return returns
    for node in ast.walk(tree):
        if isinstance(node, ast.Return) and node.value is not None:
            text = _call_to_text(node.value)
            if text:
                returns.append(text)
    return _dedupe_preserve_order(returns, limit=5)


def _extract_explicit_output_dict_keys(source: str) -> list[str]:
    keys: list[str] = []
    try:
        tree = ast.parse(textwrap.dedent(source or ""))
    except SyntaxError:
        return keys
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key in node.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                keys.append(key.value)
    return _dedupe_preserve_order(keys, limit=20)


def _render_test_observable_contract_guidance(
    target_source: str,
    *,
    full_file_source: str = "",
    contract_context_text: str = "",
) -> str:
    lines: list[str] = []
    returns = _extract_return_expressions(target_source)
    if returns:
        lines.append(
            "Проверяемый код возвращает значение, вычисленное выражением: "
            + "; ".join(returns)
            + ". В тесте сохрани результат вызова в переменную, если дальше нужно проверить созданные данные, сохраненное состояние или последующее чтение. "
              "Не сравнивай результат с заранее записанным примером из документации и не собирай такое же значение вручную из даты, имени, темы, идентификатора или других частей."
        )

    keys = _extract_explicit_output_dict_keys(target_source)
    if keys:
        lines.append(
            "Target-код явно формирует структурированные данные с ключами: "
            + ", ".join(keys)
            + ". Если тест проверяет сохраненные/возвращенные структурированные данные, проверяй именно эти ключи и значения, не добавляя и не пропуская ключи по догадке."
        )

    helper_lines: list[str] = []
    helper_source_context = "\n\n".join(
        part for part in [full_file_source, contract_context_text] if str(part or "").strip()
    )
    for helper_name, args in _extract_self_helper_calls(target_source):
        helper_source = _find_function_source_by_name(helper_source_context, helper_name)
        if not helper_source:
            continue
        accesses = _extract_attr_accesses_for_names(helper_source, args)
        if not accesses:
            continue
        for arg, attrs in accesses.items():
            helper_lines.append(
                f"self.{helper_name}({', '.join(args)}) читает {', '.join(attrs)}. "
                f"Если тест использует реальный helper-вызов, подготовь {arg} так, чтобы эти поля/методы были валидны; не передавай None или несовместимое значение для читаемых полей."
            )
    for item in _dedupe_preserve_order(helper_lines, limit=6):
        lines.append(item)

    if not lines:
        return ""
    return "\n".join(f"- {line}" for line in lines)


def _render_test_behavior_guidance(
    target_source: str,
    *,
    target_file: str = "",
    full_file_source: str = "",
    contract_context_text: str = "",
) -> str:
    source = str(target_source or "")
    if not source.strip():
        return ""

    method_names = []
    for name in re.findall(r"\bself\.([A-Za-z_][A-Za-z0-9_]*)\s*\(", source):
        if name not in method_names:
            method_names.append(name)

    bare_calls = []
    excluded = {
        "if",
        "for",
        "while",
        "return",
        "len",
        "str",
        "int",
        "float",
        "bool",
        "list",
        "dict",
        "set",
        "tuple",
        "print",
        "range",
        "isinstance",
        "super",
        "open",
    }
    for name in re.findall(r"(?<![\w.])([a-z_][A-Za-z0-9_]*)\s*\(", source):
        if name in excluded:
            continue
        if name in bare_calls:
            continue
        bare_calls.append(name)

    module_name = ""
    file_path = str(target_file or "").strip()
    if file_path.endswith(".py"):
        module_name = file_path[:-3].replace("/", ".")

    lines = []
    if method_names:
        helpers = ", ".join(method_names)
        lines.append(
            f"Target-код вызывает методы того же экземпляра через self: {helpers}. "
            "Если пользовательский запрос требует сохранить существующий путь выполнения или структуру работы метода, "
            "не подменяй эти helper-вызовы так, чтобы скрыть неверный аргумент, порядок вызовов или изменение формата данных. "
            "В остальных случаях, когда тесту нужно контролировать такой helper, подмени именно видимый instance method "
            "на объекте тестируемого класса. Данные, возвращаемые этой подменой, являются достаточной "
            "подготовкой для вызова target-метода; не создавай скрытые атрибуты состояния вроде `_items`, "
            "`_notes`, `_storage`, `_records`, если они не видны в class source."
        )
    if bare_calls:
        helpers = ", ".join(bare_calls)
        lines.append(
            f"Target-код вызывает свободные helper-функции по локальным именам: {helpers}. "
            "Предпочитай использовать реальные helper-функции и вычислять expected values через те же видимые helpers. "
            "Если подмена действительно нужна, patch должен менять binding в модуле target-кода"
            + (f" `{module_name}.<helper>`" if module_name else "")
            + ", а не исходный модуль helper-а, потому что target-код может использовать direct from-import."
        )
    observable_guidance = _render_test_observable_contract_guidance(
        target_source,
        full_file_source=full_file_source,
        contract_context_text=contract_context_text,
    )
    if observable_guidance:
        lines.append(observable_guidance)
    if not lines:
        return ""
    return "\n".join(f"- {line}" for line in lines)

def _clean_test_plan_avoid_for_prompt(avoid: Any) -> list[str]:
    """Remove avoid items that conflict with generic generated-test rules.

    The test planner can occasionally place useful built-in test resources into
    `avoid`. Passing those contradictions to the final test generator makes the
    prompt unstable: the generator sees both "use a minimal real scenario" and
    "avoid the resource needed for that scenario". This cleanup does not invent
    new requirements; it only removes generic pytest resources that are allowed
    elsewhere in the prompt.
    """
    if not isinstance(avoid, list):
        return []

    removable_markers = (
        "tmp_path",
        "pytest fixture",
        "pytest fixtures",
        "встроенные pytest fixtures",
    )
    cleaned: list[str] = []
    for item in avoid:
        text = str(item or "").strip()
        if not text:
            continue
        normalized = text.lower()
        if any(marker in normalized for marker in removable_markers):
            continue
        cleaned.append(text)
    return cleaned


def _select_test_plan_fields_for_prompt(test_plan: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    if not isinstance(test_plan, dict) or not test_plan:
        return {}
    if not fields:
        selected = dict(test_plan)
    else:
        selected = {}
        for field in fields:
            if field in test_plan:
                selected[field] = test_plan[field]
    if "avoid" in selected:
        selected["avoid"] = _clean_test_plan_avoid_for_prompt(selected.get("avoid"))
    return selected

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
    contract_context_block: str = "",
    contract_attribute_requirements_block: str = "",
    model_surfaces_text: str = "",
    required_imports_text: str = "",
    source_priority_text: str = "",
    test_behavior_guidance_text: str = "",
    constructor_guidance_text: str = "",
) -> dict[str, str]:
    target_block = _render_optional_block("Исполняемый код проверяемого метода без документации", target_source)
    example_block = _render_optional_block("Пример теста", example_text)
    related_tests_block = _render_optional_block("Связанные тесты проекта", related_tests_text)
    import_context_block = _render_optional_block("Импорты из целевого файла", import_context_text)
    inferred_symbols_block = _render_optional_block(
        "Символы проекта из target-кода",
        inferred_symbols_text,
    )
    full_file_source_block = _render_optional_block(
        "Справочный исполняемый контекст целевого файла до изменения без документации",
        full_file_source_text,
    )
    test_plan_block = _render_optional_block(
        "План теста",
        test_plan_text,
    )
    required_imports_block = _render_optional_block(
        "Required project imports",
        required_imports_text,
    )
    model_surfaces_block = _render_optional_block(
        "Visible constructor and field contracts for test data",
        model_surfaces_text,
    )
    test_behavior_guidance_block = _render_optional_block(
        "Target-derived test data strategy",
        test_behavior_guidance_text,
    )
    constructor_guidance_block = _render_optional_block(
        "Visible parent constructor contract for tests",
        constructor_guidance_text,
    )
    return {
        "operation": request.target.get("operation", "replace_symbol"),
        "insert_scope": request.target.get("insert_scope") or "",
        "expected_new_symbol_kind": request.target.get("expected_new_symbol_kind") or "",
        "parent_qualname": request.target.get("parent_qualname") or "",
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
        "source_priority_block": _render_optional_block("Приоритет источников для теста", source_priority_text),
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
        "required_imports_block": required_imports_block,
        "model_surfaces_block": model_surfaces_block,
        "test_behavior_guidance_block": test_behavior_guidance_block,
        "constructor_guidance_block": constructor_guidance_block,
        "reference_context_block": reference_context_block,
        "contract_context_block": contract_context_block,
        "contract_attribute_requirements_block": contract_attribute_requirements_block,
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
    full_file_source_text: str = "",
    compact_request_text: str,
    effective_target_symbol: str,
    anchor_symbol: str | None,
    reference_context_block: str = "",
    contract_context_block: str = "",
    contract_attribute_requirements_block: str = "",
) -> None:
    logger.info(
        "Test prompt state stage=%s operation=%s prompt_chars=%s available_user_chars=%s "
        "target_chars=%s request_chars=%s full_file_chars=%s has_full_file=%s "
        "example_chars=%s related_tests_chars=%s has_related_tests=%s "
        "import_context_chars=%s inferred_symbols_chars=%s "
        "reference_chars=%s has_reference=%s contract_context_chars=%s has_contract_context=%s contract_attribute_requirements_chars=%s has_contract_attribute_requirements=%s effective_target_symbol=%s anchor_symbol=%s",
        stage,
        requested_operation,
        prompt_len,
        available_user_chars,
        len(target_source or ""),
        len(compact_request_text or ""),
        len(full_file_source_text or ""),
        bool(str(full_file_source_text or "").strip()),
        len(example_text or ""),
        len(related_tests_text or ""),
        bool(str(related_tests_text or "").strip()),
        len(import_context_text or ""),
        len(inferred_symbols_text or ""),
        len(reference_context_block or ""),
        bool(str(reference_context_block or "").strip()),
        len(contract_context_block or ""),
        bool(str(contract_context_block or "").strip()),
        len(contract_attribute_requirements_block or ""),
        bool(str(contract_attribute_requirements_block or "").strip()),
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
    planner_result: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    pc = request.project_context or {}
    effective_test_plan = test_plan or request.test_plan or {}
    prompt_test_plan = _select_test_plan_fields_for_prompt(
        effective_test_plan,
        list(runtime_config.prompt_assembly.test_generator_plan_fields or []),
    )
    test_plan_text = _pretty(prompt_test_plan) if prompt_test_plan else ""    
    required_imports = _required_project_imports_from_symbols_for_tests(
        request.project_context or {},
        list((effective_test_plan or {}).get("must_use_symbols") or []),
    )
    request_required_imports_text = _required_project_imports_for_tests(
        request.project_context or {},
        request.change_request,
    )
    required_imports_text = "\n".join(
        dict.fromkeys(
            [
                *[line for line in required_imports if str(line or "").strip()],
                *[
                    line
                    for line in request_required_imports_text.splitlines()
                    if str(line or "").strip()
                ],
            ]
        )
    )
    target_symbol = pc.get("target_symbol") or {}
    compact_request_text = _compact_change_request_for_codegen(
        request.change_request,
        planner_result=planner_result,
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
    target_executable_source, target_docstrings_removed = _strip_docstrings_from_python_source(target_source)

    insert_scope = str(
        artifact_payload.get("insert_scope")
        or request.target.get("insert_scope")
        or ""
    ).strip()
    expected_new_symbol_kind = str(
        artifact_payload.get("expected_new_symbol_kind")
        or request.target.get("expected_new_symbol_kind")
        or ""
    ).strip()
    stripped_target_source = target_executable_source.strip()
    if insert_scope == "class_body" or expected_new_symbol_kind == "method":
        effective_target_kind = "method"
    elif stripped_target_source.startswith("class ") or "\nclass " in stripped_target_source:
        effective_target_kind = "class"

    effective_target_name = (
        effective_target_symbol.rsplit(".", 1)[-1]
        if effective_target_symbol
        else ""
    )

    # Keep an untrimmed copy for small, high-value structural facts such as
    # parent constructor signatures. The rendered full-file block may be
    # truncated heavily for prompt budget, but constructor guidance should not
    # disappear just because the visible file excerpt no longer reaches the
    # class body.
    full_file_source_for_guidance = str(pc.get("full_file_source", "") or "").strip()
    full_file_source_text, full_file_docstrings_removed = _strip_docstrings_from_python_source(full_file_source_for_guidance)
    source_priority_text = ""
    if target_source_origin == "generated_code_artifact":
        source_priority_text = (
            "Главный источник истины для теста — исполняемый код проверяемого метода без документации. "
            "Справочный контекст целевого файла и связанных методов используй только для импортов, сигнатур, стиля и окружающего кода. "
            "Документация, комментарии и примеры нужны только для общего понимания. "
            "Если пример из справочного контекста отличается от исполняемого кода, используй исполняемый код."
        )

    related_tests_text, related_test_metrics = _render_related_tests(
        pc,
        max_items=1,
        per_item_chars=500,
        strip_source_docstrings=True,
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
    contract_context_text, contract_metrics = _render_contract_context(
        pc,
        max_items=runtime_config.test_prompt_contract_symbols,
        per_item_chars=runtime_config.test_prompt_contract_symbol_chars,
        include_docstrings=False,
        strip_source_docstrings=True,
    )
    model_surfaces_text, model_surfaces_metrics = _render_model_surfaces(
        pc,
        max_chars=_block_limit(runtime_config, "generate_block_chars", "model_surfaces", 1200),
    )
    contract_metrics.update(model_surfaces_metrics)
    contract_context_block = _render_optional_block(
        "Связанные production-контракты",
        _normalize_optional_value(contract_context_text),
    )
    contract_attribute_text, contract_attribute_metrics = _render_contract_attribute_requirements(
        pc,
        max_chars=_block_limit(runtime_config, "generate_block_chars", "contract_attribute_requirements", 1600),
    )
    contract_attribute_requirements_block = _render_optional_block(
        "Contract attribute requirements for generated test data",
        _normalize_optional_value(contract_attribute_text),
    )

    import_context_text = _extract_import_context(full_file_source_text)
    inferred_symbols = _infer_project_symbols(target_executable_source)
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
            target_source=target_executable_source,
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
            contract_context_block=contract_context_block,
            contract_attribute_requirements_block=contract_attribute_requirements_block,
            model_surfaces_text=_normalize_optional_value(model_surfaces_text),
            required_imports_text=required_imports_text,
            source_priority_text=source_priority_text,
            test_behavior_guidance_text=_render_test_behavior_guidance(
                target_executable_source,
                target_file=str(request.target.get("file_path", "") or ""),
                full_file_source=full_file_source_for_guidance,
                contract_context_text=contract_context_text,
            ),
            constructor_guidance_text=_render_test_constructor_guidance(
                full_file_source=full_file_source_for_guidance,
                effective_target_symbol=effective_target_symbol,
                parent_qualname=str(request.target.get("parent_qualname") or ""),
                insert_scope=insert_scope,
                expected_new_symbol_kind=expected_new_symbol_kind,
            ),
        )
        prompt_value = template_text.format(**values)
        if "{reference_context_block}" not in template_text and values.get("reference_context_block"):
            prompt_value += values["reference_context_block"]
        if "{contract_context_block}" not in template_text and values.get("contract_context_block"):
            prompt_value += values["contract_context_block"]
        return prompt_value

    def _log(stage: str, prompt_value: str) -> None:
        _log_test_prompt_state(
            stage,
            requested_operation=requested_operation,
            available_user_chars=available_user_chars,
            prompt_len=len(prompt_value),
            target_source=target_executable_source,
            example_text=example_text,
            related_tests_text=related_tests_text,
            import_context_text=import_context_text,
            inferred_symbols_text=inferred_symbols_text,
            full_file_source_text=full_file_source_text,
            compact_request_text=compact_request_text,
            effective_target_symbol=effective_target_symbol,
            anchor_symbol=anchor_symbol,
            reference_context_block=reference_context_block,
            contract_context_block=contract_context_block,
            contract_attribute_requirements_block=contract_attribute_requirements_block,
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
    # В тестогенерации пользовательский запрос, target-код, import context и
    # contract context являются core-контекстом. Их нельзя выбрасывать только
    # ради формального попадания в старый размер prompt-а; лучше явно
    # залогировать overflow и отправить best-effort prompt.
    allow_core_context_removal = False

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

    if len(prompt) > available_user_chars and compact_request_text and allow_core_context_removal:
        compact_request_text = ""
        _record("removed compact_request_text on size limit")
        prompt = _render_prompt()
        _log("after_remove_request", prompt)

    if len(prompt) > available_user_chars and reference_context_block:
        reference_context_block = ""
        _record("removed reference_context_block on size limit")
        prompt = _render_prompt()
        _log("after_remove_reference_context", prompt)

    # Contract attribute requirements are more important than generic contract source,
    # because they directly constrain generated test data/fakes.
    if len(prompt) > available_user_chars and contract_context_block and allow_core_context_removal:
        contract_context_block = ""
        _record("removed contract_context_block on size limit")
        prompt = _render_prompt()
        _log("after_remove_contract_context", prompt)

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

    if len(prompt) > available_user_chars and target_source and allow_core_context_removal:
        target_source, _ = _truncate_text(
            target_source,
            runtime_config.test_prompt_target_truncate_chars,
        )
        _record(
            f"truncated target_source to {runtime_config.test_prompt_target_truncate_chars} on size limit"
        )
        prompt = _render_prompt()
        _log("after_truncate_target", prompt)

    if len(prompt) > available_user_chars and import_context_text and allow_core_context_removal:
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

    if not _fits_with_soft_overflow(prompt) and contract_context_block and allow_core_context_removal:
        contract_context_block = ""
        _record("removed contract_context_block on hard size overflow")
        prompt = _render_prompt()
        _log("after_remove_contract_context_hard", prompt)

    if not _fits_with_soft_overflow(prompt) and contract_attribute_requirements_block and allow_core_context_removal:
        contract_attribute_requirements_block = ""
        _record("removed contract_attribute_requirements_block on hard size overflow")
        prompt = _render_prompt()
        _log("after_remove_contract_attribute_requirements_hard", prompt)

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

    if not _fits_with_soft_overflow(prompt) and import_context_text and allow_core_context_removal:
        import_context_text = ""
        _record("removed import_context on hard size overflow")
        prompt = _render_prompt()
        _log("after_remove_import_context_hard", prompt)        

    if not full_file_source_text.strip() and not str(related_tests_text or "").strip():
        logger.warning(
            "test prompt degraded: both full_file_source and related_tests were removed; "
            "generation will rely mostly on target code"
        )
    if len(prompt) > available_user_chars + soft_overflow_chars:
        logger.warning(
            "test prompt remains over limit but core context was preserved operation=%s prompt_chars=%s available_user_chars=%s soft_overflow_chars=%s section_sizes=%s",
            requested_operation,
            len(prompt),
            available_user_chars,
            soft_overflow_chars,
            {
                "target": len(target_source),
                "request": len(compact_request_text),
                "full_file": len(full_file_source_text),
                "related_tests": len(related_tests_text or ""),
                "reference": len(reference_context_block or ""),
                "contract_context": len(contract_context_block or ""),
                "contract_attribute_requirements": len(contract_attribute_requirements_block or ""),
                "import_context": len(import_context_text),
                "inferred_symbols": len(inferred_symbols_text),
                "example": len(example_text),
            },
        )

    logger.info(
        "test prompt final blocks operation=%s prompt_chars=%s available_user_chars=%s "
        "soft_overflow_chars=%s has_request=%s has_full_file=%s has_example=%s "
        "has_related_tests=%s target_chars=%s request_chars=%s full_file_chars=%s "
        "example_chars=%s related_tests_chars=%s reference_chars=%s has_reference=%s contract_context_chars=%s has_contract_context=%s contract_attribute_requirements_chars=%s has_contract_attribute_requirements=%s",
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
        len(contract_context_block or ""),
        bool(str(contract_context_block or "").strip()),
        len(contract_attribute_requirements_block or ""),
        bool(str(contract_attribute_requirements_block or "").strip()),
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
        "test_contract_symbols_count": int(contract_metrics.get("contract_symbols_count", 0) or 0),
        "test_contract_symbol_chars": int(contract_metrics.get("contract_symbol_chars", 0) or 0),
        "test_contract_attribute_requirements_count": int(contract_attribute_metrics.get("contract_attribute_requirements_count", 0) or 0),
        "test_contract_attribute_requirements_chars": int(contract_attribute_metrics.get("contract_attribute_requirements_chars", 0) or 0),
        "test_has_example_block": bool(example_text),
        "test_has_related_tests_block": bool(str(related_tests_text or "").strip()),
        "test_has_import_context_block": bool(import_context_text),
        "test_has_inferred_symbols_block": bool(inferred_symbols_text),
        "test_has_full_file_context": bool(full_file_source_text),
        "test_has_reference_context": bool(reference_context_block),
        "test_has_contract_context": bool(contract_context_block),
        "test_has_contract_attribute_requirements": bool(contract_attribute_requirements_block),
    }
    return prompt, metrics


def build_repair_planner_user_prompt(
    template_text: str,
    request: RepairRequest,
    runtime_config: RuntimeConfig | None = None,
) -> str:
    """Build prompt for the dedicated repair planner."""
    project_context = request.project_context or {}
    target_symbol = project_context.get("target_symbol") or {}
    previous_artifact = request.previous_artifact or {}
    change_request = request.change_request or {}

    requested_operation = previous_artifact.get("operation") or request.target.get("operation") or "replace_symbol"

    module_outline_text = _normalize_optional_value(
        _render_module_outline(project_context.get("module_outline", []))
    )
    if module_outline_text:
        module_outline_text, _ = _truncate_text(
            module_outline_text,
            _block_limit(runtime_config, "repair_block_chars", "module_outline", 600),
        )

    target_rendered = _render_target_symbol(target_symbol)
    if target_rendered:
        target_rendered, _ = _truncate_text(
            target_rendered,
            _block_limit(runtime_config, "repair_block_chars", "target_source", 900),
        )
    target_rendered = _normalize_optional_value(target_rendered)

    previous_code = str(previous_artifact.get("code", "") or "")
    if previous_code:
        previous_code, _ = _truncate_text(
            previous_code,
            _block_limit(runtime_config, "repair_block_chars", "previous_code", 1200),
        )
    previous_code = _normalize_optional_value(previous_code)

    contract_context_text, _ = _render_contract_context(
        project_context,
        max_items=runtime_config.repair_max_contract_symbols if runtime_config else 4,
        per_item_chars=runtime_config.repair_max_contract_symbol_chars if runtime_config else 700,
    )
    contract_context_text = _normalize_optional_value(contract_context_text)

    allowed_api_surface_text = ""
    if "_render_allowed_api_surface" in globals():
        try:
            allowed_api_surface_text, _ = _render_allowed_api_surface(
                project_context,
                max_chars=_block_limit(runtime_config, "repair_block_chars", "allowed_api_surface", 1600),
            )
            allowed_api_surface_text = _normalize_optional_value(allowed_api_surface_text)
        except Exception:
            allowed_api_surface_text = ""

    required_repair_imports_text = _required_project_imports_for_codegen(project_context, change_request)

    if allowed_api_surface_text and contract_context_text:
        contract_context_text = (
            "Allowed API Surface (authoritative; do not invent dependency calls outside this list):\n"
            f"{allowed_api_surface_text}\n\n---\n\nRelated production contracts:\n{contract_context_text}"
        )
    elif allowed_api_surface_text:
        contract_context_text = (
            "Allowed API Surface (authoritative; do not invent dependency calls outside this list):\n"
            f"{allowed_api_surface_text}"
        )

    if required_repair_imports_text:
        contract_context_text = (
            "Required project imports for visible project symbols:\n"
            f"{required_repair_imports_text}\n\n---\n\n"
            f"{contract_context_text}"
        )

    repair_problem_block = _build_repair_problem_block(request.error_context or {})
    previous_code_block = _render_optional_block("Код, который нужно исправить", previous_code)
    target_function_block = _render_optional_block("Исходный target symbol", target_rendered)
    contract_context_block = _render_optional_block(
        "Связанные production-контракты и Allowed API Surface",
        contract_context_text,
    )
    module_outline_block = _render_optional_block("Структура модуля", module_outline_text)
    compact_request = _compact_change_request_for_codegen(change_request)

    values = {
        "requested_operation": str(requested_operation or ""),
        "target_file": str(request.target.get("file_path") or previous_artifact.get("target_file") or ""),
        "target_symbol": str(
            request.target.get("qualname")
            or previous_artifact.get("target_qualname")
            or previous_artifact.get("target_symbol")
            or ""
        ),
        "insert_after": str(previous_artifact.get("insert_after") or previous_artifact.get("target_qualname") or ""),
        "request": compact_request,
        "repair_problem_block": repair_problem_block,
        "previous_code_block": previous_code_block,
        "target_function_block": target_function_block,
        "contract_context_block": contract_context_block,
        "module_outline_block": module_outline_block,
    }

    return template_text.format(**values)


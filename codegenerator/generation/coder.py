from __future__ import annotations
from codegenerator.parsing.response_parser import parse_llm_json, normalize_code_fields

CANONICAL_OPERATIONS = {"replace_symbol", "add_symbol", "insert_after_symbol"}


def _normalize_operation(operation: str) -> str:
    value = str(operation or '').strip().lower()
    mapping = {
        'modify_function': 'replace_symbol',
        'replace_function': 'replace_symbol',
        'replace_method': 'replace_symbol',
        'replace_symbol': 'replace_symbol',
        'modify_symbol': 'replace_symbol',
        'add_function': 'add_symbol',
        'add_method': 'add_symbol',
        'add_symbol': 'add_symbol',
        'insert_after_function': 'insert_after_symbol',
        'insert_after_symbol': 'insert_after_symbol',
    }
    return mapping.get(value, value)


def _normalize_insert_scope(value) -> str | None:
    raw = str(value or '').strip().lower()
    if not raw:
        return None
    mapping = {
        'class': 'class_body',
        'class_body': 'class_body',
        'method': 'class_body',
        'module': 'module_body',
        'module_body': 'module_body',
        'top_level': 'module_body',
        'top-level': 'module_body',
    }
    return mapping.get(raw, raw)

def _strip_leading_imports_for_insert_after(code: str) -> str:
    lines = code.splitlines()
    result: list[str] = []
    skipping = True

    for line in lines:
        stripped = line.strip()

        if skipping:
            if not stripped:
                continue
            if stripped.startswith("import ") or stripped.startswith("from "):
                continue
            skipping = False

        result.append(line)

    return _dedent_insert_after_code("\n".join(result))


def _dedent_insert_after_code(code: str) -> str:
    """Normalize code returned for insert_after_symbol.

    The model sometimes returns a class-body method with outer class indentation,
    or a decorated method as ``@decorator`` followed by an indented ``def``.
    The artifact contract expects the new symbol body without the surrounding
    class indent; the applier will add class indentation later.
    """
    raw_lines = str(code or "").splitlines()
    while raw_lines and not raw_lines[0].strip():
        raw_lines.pop(0)
    while raw_lines and not raw_lines[-1].strip():
        raw_lines.pop()
    if not raw_lines:
        return ""

    nonblank = [line for line in raw_lines if line.strip()]
    indents = [len(line) - len(line.lstrip(" ")) for line in nonblank]
    common_indent = min(indents) if indents else 0
    if common_indent > 0:
        raw_lines = [line[common_indent:] if len(line) >= common_indent else line.lstrip() for line in raw_lines]

    # A common failure for @property is:
    #   @property
    #       def note_id(...):
    #           ...
    # Align the first def/async def after leading decorators with those decorators.
    first_nonblank_idx = next((idx for idx, line in enumerate(raw_lines) if line.strip()), 0)
    if raw_lines[first_nonblank_idx].lstrip().startswith("@"):
        def_idx = None
        for idx in range(first_nonblank_idx + 1, len(raw_lines)):
            stripped = raw_lines[idx].lstrip()
            if stripped.startswith("def ") or stripped.startswith("async def "):
                def_idx = idx
                break
            if stripped and not stripped.startswith("@"):  # not a decorator block anymore
                break
        if def_idx is not None:
            def_indent = len(raw_lines[def_idx]) - len(raw_lines[def_idx].lstrip(" "))
            decorator_indent = len(raw_lines[first_nonblank_idx]) - len(raw_lines[first_nonblank_idx].lstrip(" "))
            if def_indent > decorator_indent:
                shift = def_indent - decorator_indent
                raw_lines = [
                    (line[shift:] if idx >= def_idx and line.startswith(" " * shift) else line)
                    for idx, line in enumerate(raw_lines)
                ]

    return "\n".join(raw_lines).lstrip()


def _normalize_expected_new_symbol_kind(value) -> str | None:
    raw = str(value or '').strip().lower()
    if not raw:
        return None
    mapping = {
        'property': 'method',
        'prop': 'method',
        'method': 'method',
        'function': 'function',
        'class': 'class',
    }
    return mapping.get(raw, raw)


def _normalize_import_changes(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    result: list[dict] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        action = str(item.get('action') or '').strip()
        module = str(item.get('module') or '').strip()
        if action not in {'add_import', 'add_from_import'} or not module:
            continue
        normalized = {'action': action, 'module': module}
        if action == 'add_import':
            alias = str(item.get('alias') or '').strip()
            if alias:
                normalized['alias'] = alias
        else:
            names = [str(name).strip() for name in (item.get('names') or []) if str(name).strip()]
            if not names:
                continue
            normalized['names'] = names
        result.append(normalized)
    return result

def parse_code_response(content: str) -> dict:
    parsed = normalize_code_fields(parse_llm_json(content))
    required = ['target_file', 'operation', 'code']
    missing = [k for k in required if k not in parsed]
    if missing:
        raise ValueError(f"code result is missing required keys: {', '.join(missing)}")

    parsed['operation'] = _normalize_operation(str(parsed['operation']))
    if parsed['operation'] not in CANONICAL_OPERATIONS:
        raise ValueError("code result field 'operation' must be one of replace_symbol, add_symbol, insert_after_symbol")

    if parsed['operation'] == 'insert_after_symbol':
        parsed['code'] = _strip_leading_imports_for_insert_after(str(parsed.get('code') or ''))

    parsed['insert_scope'] = _normalize_insert_scope(parsed.get('insert_scope'))
    parsed['expected_new_symbol_kind'] = _normalize_expected_new_symbol_kind(parsed.get('expected_new_symbol_kind'))
    parsed['parent_qualname'] = str(parsed.get('parent_qualname') or '').strip() or None
    parsed['import_changes'] = _normalize_import_changes(parsed.get('import_changes'))

    return parsed

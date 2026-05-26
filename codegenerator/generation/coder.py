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

    return "\n".join(result).lstrip()


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
    parsed['expected_new_symbol_kind'] = str(parsed.get('expected_new_symbol_kind') or '').strip() or None
    parsed['parent_qualname'] = str(parsed.get('parent_qualname') or '').strip() or None
    parsed['import_changes'] = _normalize_import_changes(parsed.get('import_changes'))

    return parsed

from __future__ import annotations
import ast

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


def _from_import_alias_text(alias: ast.alias) -> str:
    if alias.asname:
        return f"{alias.name} as {alias.asname}"
    return alias.name


def _import_change_from_string(value: str) -> list[dict]:
    text = str(value or '').strip()
    if not text:
        raise ValueError("import_changes contains an empty import string")

    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        raise ValueError(
            "import_changes string entries must be valid Python import statements"
        ) from exc

    statements = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    if len(tree.body) != len(statements) or not statements:
        raise ValueError(
            "import_changes string entries must contain only import statements"
        )

    result: list[dict] = []
    for node in statements:
        if isinstance(node, ast.Import):
            for alias in node.names:
                item = {'action': 'add_import', 'module': alias.name}
                if alias.asname:
                    item['alias'] = alias.asname
                result.append(item)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                raise ValueError(
                    "import_changes string entries must use absolute imports, not relative imports"
                )
            module = str(node.module or '').strip()
            if not module:
                raise ValueError(
                    "import_changes from-import string entries must include a module"
                )
            names = [_from_import_alias_text(alias) for alias in node.names]
            if any(name == '*' for name in names):
                raise ValueError("import_changes does not support star imports")
            if not names:
                raise ValueError(
                    "import_changes from-import string entries must include imported names"
                )
            result.append({'action': 'add_from_import', 'module': module, 'names': names})
    return result


def _import_change_names(item: dict) -> list[str]:
    raw_names = item.get('names')
    if isinstance(raw_names, str):
        return [part.strip() for part in raw_names.split(',') if part.strip()]
    return [str(name).strip() for name in (raw_names or []) if str(name).strip()]


def _normalize_import_change_item(item) -> dict:
    allowed_actions = {'add_import', 'add_from_import', 'remove_import', 'remove_from_import'}
    if not isinstance(item, dict):
        raise ValueError(
            "import_changes entries must be objects like "
            '{"action":"add_from_import","module":"pkg.mod","names":["Name"]}; '
            "string import statements are accepted only when they are valid Python imports"
        )
    action = str(item.get('action') or '').strip()
    module = str(item.get('module') or '').strip()
    if action not in allowed_actions:
        raise ValueError(
            "import_changes entry has unsupported action; expected one of "
            "add_import, add_from_import, remove_import, remove_from_import"
        )
    if not module:
        raise ValueError("import_changes entry must include a non-empty module")

    names = _import_change_names(item)
    # LLMs sometimes return {"action":"add_import","module":"pathlib","names":["Path"]}
    # when the intended Python statement is ``from pathlib import Path``.
    # Preserve that intent as a schema/protocol normalization instead of silently
    # dropping ``names`` and turning the artifact into ``import pathlib``.
    if names and action == 'add_import':
        action = 'add_from_import'
    elif names and action == 'remove_import':
        action = 'remove_from_import'

    normalized = {'action': action, 'module': module}
    if action in {'add_import', 'remove_import'}:
        alias = str(item.get('alias') or item.get('asname') or '').strip()
        if alias:
            normalized['alias'] = alias
    else:
        if not names:
            raise ValueError(f"{action} import_changes entry must include names")
        normalized['names'] = names
    return normalized



def _code_uses_name(code: str | None, name: str) -> bool:
    if not code or not name:
        return False
    return any(node.id == name for node in ast.walk(ast.parse(code)) if isinstance(node, ast.Name)) if _can_parse_code(code) else bool(__import__('re').search(rf"\b{name}\b", code))


def _can_parse_code(code: str) -> bool:
    try:
        ast.parse(code)
        return True
    except SyntaxError:
        return False




def _imported_names_from_code_for_module(code: str | None, module: str) -> list[str]:
    if not code or not module or not _can_parse_code(code):
        return []
    names: list[str] = []
    for node in ast.walk(ast.parse(code)):
        if not isinstance(node, ast.ImportFrom) or node.module != module:
            continue
        for alias in node.names:
            if alias.name == '*':
                continue
            imported_name = alias.asname or alias.name
            if imported_name and imported_name not in names:
                names.append(imported_name)
    return names


def _well_known_short_names_for_module(module: str) -> tuple[str, ...]:
    return {
        'PyQt5.QtWidgets': ('QFileDialog',),
        'pathlib': ('Path', 'PurePath', 'PurePosixPath', 'PureWindowsPath'),
    }.get(module, ())

def _normalize_import_change_for_code(item: dict, code: str | None) -> dict:
    action = str(item.get('action') or '').strip()
    module = str(item.get('module') or '').strip()
    if not code or action not in {'add_import', 'remove_import'}:
        return item

    alias = str(item.get('alias') or '').strip()
    if alias and alias[:1].isupper() and _code_uses_name(code, alias):
        converted = {'action': 'add_from_import' if action == 'add_import' else 'remove_from_import', 'module': module, 'names': [alias]}
        return converted

    imported_names = _imported_names_from_code_for_module(code, module)
    if imported_names:
        return {'action': 'add_from_import' if action == 'add_import' else 'remove_from_import', 'module': module, 'names': imported_names}

    if not _code_uses_name(code, module.split('.', 1)[0]):
        names = [name for name in _well_known_short_names_for_module(module) if _code_uses_name(code, name)]
        if names:
            return {'action': 'add_from_import' if action == 'add_import' else 'remove_from_import', 'module': module, 'names': names}

    return item


def _dedupe_import_changes(items: list[dict]) -> list[dict]:
    result: list[dict] = []
    seen: set[tuple] = set()
    for item in items:
        key = (
            item.get('action'),
            item.get('module'),
            tuple(item.get('names') or []),
            item.get('alias'),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result

def _normalize_import_changes(value, *, code: str | None = None) -> list[dict]:
    if value is None:
        return []
    if isinstance(value, str):
        return _import_change_from_string(value)
    if not isinstance(value, list):
        raise ValueError("import_changes must be a JSON array")

    result: list[dict] = []
    for item in value:
        if isinstance(item, str):
            normalized_items = _import_change_from_string(item)
        else:
            normalized_items = [_normalize_import_change_item(item)]
        for normalized_item in normalized_items:
            result.append(_normalize_import_change_for_code(normalized_item, code))
    return _dedupe_import_changes(result)

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
    parsed['import_changes'] = _normalize_import_changes(parsed.get('import_changes'), code=str(parsed.get('code') or ''))

    return parsed

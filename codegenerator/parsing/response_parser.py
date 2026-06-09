from __future__ import annotations

import json
import re
from typing import Any

from codegenerator.parsing.json_utils import parse_json_object

JSON_BLOCK_RE = re.compile(r'\{.*\}', re.DOTALL)


def parse_llm_json(content: str) -> dict[str, Any]:
    try:
        return parse_json_object(content)
    except Exception as direct_error:
        match = JSON_BLOCK_RE.search(content)
        if match:
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
            else:
                if not isinstance(parsed, dict):
                    raise ValueError("Model output must be a JSON object")
                return parsed

        recovered = _parse_truncated_json_object(content)
        if recovered is not None:
            return recovered
        raise direct_error


def _parse_truncated_json_object(content: str) -> dict[str, Any] | None:
    """Recover a JSON object truncated after a complete value.

    This intentionally only closes unbalanced JSON brackets/braces. It does not
    rewrite field names, string contents, values, or Python code embedded in JSON.
    """
    start = content.find('{')
    if start < 0:
        return None
    candidate = content[start:].strip()
    if not candidate.startswith('{'):
        return None

    stack: list[str] = []
    in_string = False
    escape = False
    for char in candidate:
        if in_string:
            if escape:
                escape = False
            elif char == '\\':
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in '{[':
            stack.append(char)
        elif char in '}]':
            if not stack:
                return None
            opener = stack.pop()
            if (opener, char) not in {('{', '}'), ('[', ']')}:
                return None

    if in_string or not stack:
        return None

    closers = ''.join('}' if opener == '{' else ']' for opener in reversed(stack))
    try:
        recovered = json.loads(candidate + closers)
    except json.JSONDecodeError:
        return None
    if not isinstance(recovered, dict):
        raise ValueError("Model output must be a JSON object")
    return recovered


def normalize_code_fields(parsed: dict[str, Any]) -> dict[str, Any]:
    aliases = {
        'target_symbol': 'target_qualname',
        'file_path': 'target_file',
        'replacement_code': 'code',
        'edit_operation': 'operation',
    }
    out = dict(parsed)
    for old, new in aliases.items():
        if old in out and new not in out:
            out[new] = out[old]
    return out

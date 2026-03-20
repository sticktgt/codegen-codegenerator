from __future__ import annotations
import json, re
from typing import Any
from codegenerator.parsing.json_utils import parse_json_object

JSON_BLOCK_RE = re.compile(r'\{.*\}', re.DOTALL)

def parse_llm_json(content: str) -> dict[str, Any]:
    try:
        return parse_json_object(content)
    except Exception:
        match = JSON_BLOCK_RE.search(content)
        if not match:
            raise
        return json.loads(match.group(0))

def normalize_code_fields(parsed: dict[str, Any]) -> dict[str, Any]:
    aliases = {
        'target_symbol':'target_qualname',
        'file_path':'target_file',
        'replacement_code':'code',
        'edit_operation':'operation',
    }
    out = dict(parsed)
    for old,new in aliases.items():
        if old in out and new not in out:
            out[new]=out[old]
    return out

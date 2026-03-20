from __future__ import annotations

import json
from typing import Any


def parse_json_object(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON returned by model: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("Model output must be a JSON object")

    return data


def require_keys(data: dict[str, Any], required_keys: list[str], object_name: str) -> None:
    missing = [key for key in required_keys if key not in data]
    if missing:
        raise ValueError(f"{object_name} is missing required keys: {', '.join(missing)}")
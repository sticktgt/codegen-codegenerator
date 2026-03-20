from __future__ import annotations

import re
from typing import Any


VALUE_ERROR_PATTERN = re.compile(
    r"ValueError\(\s*(['\"])(.*?)\1\s*\)",
    re.DOTALL,
)

LATIN_PATTERN = re.compile(r"[A-Za-z]")


def validate_russian_error_messages(code: str) -> dict[str, Any]:
    messages: list[str] = []

    for match in VALUE_ERROR_PATTERN.finditer(code):
        message_text = match.group(2)
        messages.append(message_text)

    violations = [message for message in messages if LATIN_PATTERN.search(message)]

    return {
        "ok": len(violations) == 0,
        "checked_messages": messages,
        "violations": violations,
    }
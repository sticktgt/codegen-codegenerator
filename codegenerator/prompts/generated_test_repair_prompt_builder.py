from __future__ import annotations

from typing import Any


class GeneratedTestRepairPromptBuilder:
    """Deprecated placeholder. Generated-test auto-fix is disabled."""

    def __init__(self, template: str) -> None:
        self.template = template

    def build(self, request: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        raise RuntimeError("Generated-test auto-fix is disabled")

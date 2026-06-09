from __future__ import annotations

from codegenerator.orchestration.generation_service import repair


def test_repair_entrypoint_remains_available() -> None:
    assert callable(repair)

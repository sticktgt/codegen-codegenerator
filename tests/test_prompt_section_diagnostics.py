from __future__ import annotations

from codegenerator.orchestration.generation_service import generate, generate_test, repair, review_generated_test_failure


def test_generation_service_public_entrypoints_are_available() -> None:
    assert callable(generate)
    assert callable(repair)
    assert callable(generate_test)
    assert callable(review_generated_test_failure)

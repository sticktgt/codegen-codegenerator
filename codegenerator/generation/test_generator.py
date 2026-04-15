from __future__ import annotations
from pathlib import Path
from codegenerator.parsing.response_parser import parse_llm_json
from codegenerator.models.requests import GenerationRequest

def build_generated_test_filename(request: GenerationRequest) -> str:
    return f"tests/test_generated_{request.request_id.replace('-', '_')}.py"

def parse_test_response(content: str, expected_test_file: str) -> dict:
    parsed = parse_llm_json(content)
    missing = [k for k in ["test_file", "code"] if k not in parsed]
    if missing:
        raise ValueError(
            f"generated test result is missing required keys: {', '.join(missing)}"
        )

    if str(parsed["test_file"]).strip() != expected_test_file:
        raise ValueError(
            f"generated test result field 'test_file' must be exactly '{expected_test_file}'"
        )

    code = str(parsed["code"] or "")
    if not code.strip():
        raise ValueError("generated test code must not be empty")

    if "```" in code:
        raise ValueError("generated test code must not contain markdown fences")

    return {
        "test_file": expected_test_file,
        "code": code,
    }
from __future__ import annotations
from pathlib import Path
import ast
from codegenerator.parsing.response_parser import parse_llm_json
from codegenerator.models.requests import GenerationRequest


def build_generated_test_filename(request: GenerationRequest) -> str:
    return f"tests/test_generated_{request.request_id.replace('-', '_')}.py"




def _validate_python_syntax(code: str) -> None:
    try:
        ast.parse(code)
    except SyntaxError as exc:
        location = f"line {exc.lineno}, column {exc.offset}" if exc.lineno else "unknown location"
        detail = exc.msg or type(exc).__name__
        raise ValueError(f"generated test code must be valid Python syntax: {detail} at {location}") from exc


def _strip_trailing_generated_test_format_artifacts(code: str) -> tuple[str, list[dict[str, str]]]:
    """Strip narrow transport-format artifacts from the test code field.

    This is intentionally conservative: it only removes trailing lines that are
    impossible Python on their own and only when the original code does not
    parse but the stripped code parses. The generated test logic is not changed.
    """
    if not code.strip():
        return code, []

    try:
        ast.parse(code)
        return code, []
    except SyntaxError:
        pass

    lines = code.splitlines()
    stripped_count = 0
    while lines and lines[-1].strip() in {"}", "```"}:
        lines.pop()
        stripped_count += 1

    if not stripped_count:
        return code, []

    candidate = "\n".join(lines).rstrip() + "\n"
    try:
        ast.parse(candidate)
    except SyntaxError:
        return code, []

    return candidate, [
        {
            "code": "generated_test_code_trailing_format_artifact_stripped",
            "message": "Модель вернула pytest-код с лишним хвостовым форматным символом; символ был удален перед проверкой синтаксиса.",
        }
    ]


def parse_test_response(content: str, expected_test_file: str) -> dict:
    parsed = parse_llm_json(content)

    missing = [k for k in ["test_file", "code"] if k not in parsed]
    if missing:
        present_keys = sorted(str(k) for k in parsed.keys())
        raise ValueError(
            "generated test result is missing required keys: "
            f"{', '.join(missing)}; present keys: {present_keys}"
        )

    if str(parsed["test_file"]).strip() != expected_test_file:
        raise ValueError(
            f"generated test result field 'test_file' must be exactly '{expected_test_file}'"
        )

    code = str(parsed["code"] or "")
    if not code.strip():
        raise ValueError("generated test code must not be empty")

    code, format_warnings = _strip_trailing_generated_test_format_artifacts(code)

    if "```" in code:
        raise ValueError("generated test code must not contain markdown fences")

    _validate_python_syntax(code)

    return {
        "test_file": expected_test_file,
        "code": code,
        "format_warnings": format_warnings,
    }


def extract_test_function_names(code: str) -> list[str]:
    result: list[str] = []
    for line in (code or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("def test_") and stripped.endswith(":"):
            name = stripped[len("def "):].split("(", 1)[0].strip()
            if name:
                result.append(name)
    return result

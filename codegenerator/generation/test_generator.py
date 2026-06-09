from __future__ import annotations
from pathlib import Path
import ast
import json
import re
from codegenerator.parsing.response_parser import parse_llm_json
from codegenerator.models.requests import GenerationRequest


def build_generated_test_filename(request: GenerationRequest) -> str:
    return f"tests/test_generated_{request.request_id.replace('-', '_')}.py"



def _recover_unterminated_code_string_payload(content: str) -> tuple[dict, list[dict[str, str]]] | None:
    """Recover a generated-test JSON payload with an unterminated `code` string.

    This accepts only the narrow transport failure where `test_file` is a valid
    JSON string and the remaining payload is the escaped body of the `code`
    string. It does not rewrite Python code or infer missing imports/asserts.
    """
    text = (content or "").strip()
    if not text.startswith("{"):
        return None

    test_file_match = re.search(r'"test_file"\s*:\s*("(?:\\.|[^"\\])*")', text, re.DOTALL)
    code_match = re.search(r'"code"\s*:\s*"', text, re.DOTALL)
    if not test_file_match or not code_match:
        return None

    try:
        test_file = json.loads(test_file_match.group(1))
    except json.JSONDecodeError:
        return None

    raw_code_body = text[code_match.end():].strip()
    if raw_code_body.endswith("}"):
        raw_code_body = raw_code_body[:-1].rstrip()
    if raw_code_body.endswith("```"):
        raw_code_body = raw_code_body[:-3].rstrip()

    # If the code string was actually terminated, let the normal JSON parser
    # handle the payload so this path stays limited to the malformed case.
    if raw_code_body.endswith('"') and not raw_code_body.endswith('\\"'):
        return None

    try:
        code = json.loads('"' + raw_code_body + '"')
    except json.JSONDecodeError:
        return None

    if not isinstance(test_file, str) or not isinstance(code, str) or not code.strip():
        return None

    return {"test_file": test_file, "code": code}, [
        {
            "code": "generated_test_json_unterminated_code_string_recovered",
            "message": "Модель вернула generated test JSON с незакрытым строковым полем code; parser восстановил только транспортную оболочку JSON без изменения Python-кода.",
        }
    ]


def _parse_test_response_payload(content: str) -> tuple[dict, list[dict[str, str]]]:
    """Parse generated-test JSON and keep narrow, visible format repairs.

    Some models occasionally return a fully usable JSON object but omit the
    final closing brace after the code string. Accept only this narrow shape and
    attach a warning so the caller can expose that the JSON contract was not
    followed exactly.
    """
    try:
        return parse_llm_json(content), []
    except Exception as original_exc:
        recovered_code_string = _recover_unterminated_code_string_payload(content)
        if recovered_code_string is not None:
            return recovered_code_string

        text = (content or "").strip()
        if not text.startswith("{"):
            raise
        for suffix in ("}", "}}"):
            candidate = text + suffix
            try:
                parsed = parse_llm_json(candidate)
            except Exception:
                continue
            return parsed, [
                {
                    "code": "generated_test_json_missing_trailing_brace_repaired",
                    "message": "Модель вернула generated test JSON без завершающей фигурной скобки; parser добавил недостающую скобку и сохранил предупреждение.",
                }
            ]
        raise original_exc


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
    parsed, format_warnings = _parse_test_response_payload(content)

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

    code, code_format_warnings = _strip_trailing_generated_test_format_artifacts(code)
    format_warnings.extend(code_format_warnings)

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

from __future__ import annotations

from codegenerator.generation.test_generator import parse_test_response


def test_test_response_parser_accepts_valid_json_payload() -> None:
    payload = '{"test_file":"tests/test_generated.py","code":"def test_generated():\\n    assert True\\n"}'

    parsed = parse_test_response(payload, 'tests/test_generated.py')

    assert parsed['test_file'] == 'tests/test_generated.py'
    assert 'def test_generated' in parsed['code']


def test_test_response_parser_recovers_unterminated_code_string_transport_error() -> None:
    payload = (
        '{\n'
        '  "test_file": "tests/test_generated.py",\n'
        '  "code": "def test_generated():\\n    assert True\\n}'
    )

    parsed = parse_test_response(payload, 'tests/test_generated.py')

    assert parsed['test_file'] == 'tests/test_generated.py'
    assert parsed['code'] == 'def test_generated():\n    assert True\n'
    assert parsed['format_warnings'][0]['code'] == 'generated_test_json_unterminated_code_string_recovered'

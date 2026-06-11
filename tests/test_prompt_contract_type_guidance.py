from __future__ import annotations

from pathlib import Path


def test_coder_and_repair_prompts_keep_visible_signature_guidance() -> None:
    root = Path(__file__).resolve().parents[1]
    coder = (root / 'prompts' / 'coder_user_template.txt').read_text(encoding='utf-8')
    repair = (root / 'prompts' / 'repair_user_template.txt').read_text(encoding='utf-8')

    assert 'видим' in coder.lower()
    assert 'сигнатур' in coder.lower()
    assert 'видим' in repair.lower()
    assert 'сигнатур' in repair.lower()

import json

from codegenerator.generation.coder import parse_code_response


def test_import_changes_normalize_short_class_and_path_imports() -> None:
    payload = {
        'target_file': 'editor/editor_window.py',
        'operation': 'replace_symbol',
        'target_qualname': 'editor.editor_window.EditorWindow.open_note',
        'code': (
            'def open_note(self):\n'
            '    selected = Path(file_name)\n'
            '    QFileDialog.getOpenFileName(self)\n'
        ),
        'import_changes': [
            {'action': 'add_import', 'module': 'pathlib'},
            {'action': 'add_import', 'module': 'PyQt5.QtWidgets', 'alias': 'QFileDialog'},
        ],
    }

    parsed = parse_code_response(json.dumps(payload, ensure_ascii=False))

    assert parsed['import_changes'] == [
        {'action': 'add_from_import', 'module': 'pathlib', 'names': ['Path']},
        {'action': 'add_from_import', 'module': 'PyQt5.QtWidgets', 'names': ['QFileDialog']},
    ]


def test_import_changes_normalize_module_import_with_local_from_import() -> None:
    payload = {
        'target_file': 'editor/editor_window.py',
        'operation': 'replace_symbol',
        'target_qualname': 'editor.editor_window.EditorWindow.open_note',
        'code': (
            'def open_note(self):\n'
            '    from PyQt5.QtWidgets import QFileDialog\n'
            '    return QFileDialog.getOpenFileName(self)\n'
        ),
        'import_changes': [
            {'action': 'add_import', 'module': 'PyQt5.QtWidgets'},
        ],
    }

    parsed = parse_code_response(json.dumps(payload, ensure_ascii=False))

    assert parsed['import_changes'] == [
        {'action': 'add_from_import', 'module': 'PyQt5.QtWidgets', 'names': ['QFileDialog']},
    ]


def test_repair_response_normalizes_import_changes_using_repair_code() -> None:
    from codegenerator.generation.repair import parse_repair_response

    payload = {
        'target_file': 'editor/editor_window.py',
        'operation': 'replace_symbol',
        'target_qualname': 'editor.editor_window.EditorWindow.open_note',
        'code': (
            'def open_note(self):\n'
            '    selected = Path(file_name)\n'
            '    return QFileDialog.getOpenFileName(self), selected\n'
        ),
        'import_changes': [
            {'action': 'add_import', 'module': 'pathlib'},
            {'action': 'add_import', 'module': 'PyQt5.QtWidgets'},
        ],
    }

    parsed = parse_repair_response(json.dumps(payload, ensure_ascii=False))

    assert parsed['import_changes'] == [
        {'action': 'add_from_import', 'module': 'pathlib', 'names': ['Path']},
        {'action': 'add_from_import', 'module': 'PyQt5.QtWidgets', 'names': ['QFileDialog']},
    ]


def test_compact_contract_prioritizes_referenced_calls_without_type_sensitive_flag() -> None:
    from codegenerator.prompts.prompt_builder import _render_compact_target_contract

    project_context = {
        'target_symbol': {
            'qualname': 'editor.editor_window.EditorWindow.open_note',
            'file_path': 'editor/editor_window.py',
        },
        'allowed_api_surface': {
            'dependencies': [
                {
                    'access_path': 'self.storage',
                    'type_name': 'NoteStorage',
                    'allowed_methods': [
                        {'name': 'generate_filename', 'signature': 'def generate_filename(self, note: Note) -> str:'},
                        {'name': 'get_save_path', 'signature': 'def get_save_path(self, note: Note) -> Path:'},
                        {'name': 'save', 'signature': 'def save(self, note: Note) -> str:'},
                        {'name': 'load', 'signature': 'def load(self, note_id: str) -> Note:'},
                        {'name': 'search_by_date', 'signature': 'def search_by_date(self, date: Optional[datetime]) -> List[Note]:'},
                        {'name': 'search_by_content', 'signature': 'def search_by_content(self, query: str) -> List[Note]:'},
                        {'name': 'find_note_file_by_id', 'signature': 'def find_note_file_by_id(self, note_id: str) -> Path:'},
                        {'name': 'get_all_note_files', 'signature': 'def get_all_note_files(self) -> List[Path]:'},
                        {'name': 'load_from_file', 'signature': 'def load_from_file(self, file_path: Path) -> Note:'},
                    ],
                }
            ]
        },
    }
    planner_result = {
        'implementation_constraints': ['Для загрузки заметки использовать self.storage.load_from_file(file_path)'],
    }

    text, metrics = _render_compact_target_contract(
        project_context,
        {'title': 'Открытие заметки'},
        planner_result=planner_result,
        include_type_sensitive_contracts=False,
    )

    visible_calls_line = next(line for line in text.splitlines() if line.startswith('Видимые dependency/project calls:'))
    assert 'load_from_file(self, file_path: Path)' in visible_calls_line
    assert 'Type-sensitive project calls' not in text
    assert metrics['compact_target_contract_type_sensitive_calls'] == 0


def test_type_sensitive_reference_text_does_not_include_registry_details() -> None:
    from codegenerator.prompts.prompt_builder import _render_compact_target_contract

    project_context = {
        'target_symbol': {'qualname': 'editor.editor_window.EditorWindow.open_note'},
        'allowed_api_surface': {
            'dependencies': [
                {
                    'access_path': 'self.storage',
                    'type_name': 'NoteStorage',
                    'allowed_methods': [
                        {'name': 'save', 'signature': 'def save(self, note: Note) -> str:'},
                        {'name': 'load_from_file', 'signature': 'def load_from_file(self, file_path: Path) -> Note:'},
                    ],
                }
            ]
        },
    }
    error_context = {
        'verification_summary': {
            'failed_blocks': [
                {
                    'issues': [
                        {
                            'code': 'contract_call_argument_type_mismatch',
                            'message': 'self.storage.load_from_file передает str, ожидается Path',
                        }
                    ],
                    'details': {
                        'known_contract_call_specs': [
                            {'name': 'save', 'signature': 'def save(self, note: Note) -> str:'},
                        ]
                    },
                }
            ]
        }
    }

    text, _ = _render_compact_target_contract(
        project_context,
        {'title': 'Открытие заметки'},
        error_context=error_context,
        include_type_sensitive_contracts=True,
    )

    type_line = next(line for line in text.splitlines() if line.startswith('Type-sensitive project calls:'))
    assert 'load_from_file' in type_line
    assert 'save(self, note: Note)' not in type_line

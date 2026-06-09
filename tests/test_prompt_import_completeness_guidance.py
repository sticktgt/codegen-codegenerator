from __future__ import annotations

from pathlib import Path


def test_coder_and_repair_prompts_keep_import_changes_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    coder = (root / 'prompts' / 'coder_user_template.txt').read_text(encoding='utf-8')
    repair = (root / 'prompts' / 'repair_user_template.txt').read_text(encoding='utf-8')

    assert 'import_changes' in coder
    assert 'import_changes' in repair
    assert 'Не добавляй import в code' in coder or 'Не добавляй import-строки внутрь code' in coder

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

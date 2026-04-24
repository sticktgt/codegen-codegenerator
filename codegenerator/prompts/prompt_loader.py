from __future__ import annotations
from pathlib import Path
from codegenerator.config import RuntimeConfig

def read_prompt_file(path: str | Path) -> str:
    p = Path(path)
    if not p.is_absolute():
        p = Path(__file__).resolve().parents[2] / path
    if not p.exists():
        raise FileNotFoundError(f'Prompt file not found: {p}')
    return p.read_text(encoding='utf-8')

def load_prompts(config: RuntimeConfig) -> dict[str, str]:
    return {
        'system_rules': read_prompt_file(config.prompts.system_rules),
        'planner_user_template': read_prompt_file(config.prompts.planner_user_template),
        'coder_user_template': read_prompt_file(config.prompts.coder_user_template),
        'repair_user_template': read_prompt_file(config.prompts.repair_user_template),
        'test_generator_user_template': read_prompt_file(config.prompts.test_generator_user_template),
        'test_generator_example_source': read_prompt_file(config.prompts.test_generator_example),
        'test_planner_user_template': read_prompt_file(config.prompts.test_planner_user_template),
    }

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import yaml

@dataclass(slots=True)
class OllamaSettings:
    base_url: str
    timeout_sec: int
    think: bool | None
    temperature: float
    num_ctx: int
    num_predict: int
    keep_alive: int | str
    options: dict[str, Any]

@dataclass(slots=True)
class ModelsSettings:
    planner_model: str
    coder_model: str
    test_generator_model: str
    repair_model: str

@dataclass(slots=True)
class PromptSettings:
    system_rules: str
    planner_user_template: str
    coder_user_template: str
    repair_user_template: str
    test_generator_user_template: str
    test_generator_example: str

@dataclass(slots=True)
class TraceSettings:
    save_to_file: bool
    show_prompts: bool
    show_raw_llm_output: bool
    output_dir: str

@dataclass(slots=True)
class RuntimeConfig:
    ollama: OllamaSettings
    models: ModelsSettings
    prompts: PromptSettings
    defaults_constraints: list[str]
    repair_enabled: bool
    max_repair_attempts: int
    test_generation_mode: str
    test_generator_max_example_tests: int
    trace: TraceSettings
    config_path: str


def load_config(config_path: str | Path) -> RuntimeConfig:
    path = Path(config_path)
    data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    llm = data.get('llm') or {}
    oll = llm.get('ollama') or {}
    cg = data.get('codegenerator') or {}
    ce = data.get('code_edit') or {}
    prompts_cfg = cg.get('prompts') or ce.get('prompts') or {}
    models_cfg = cg.get('models') or ce.get('llm') or {}
    generation_cfg = cg.get('generation') or ce.get('llm') or {}
    defaults = cg.get('defaults') or ce.get('defaults') or {}
    trace = cg.get('trace') or ce.get('trace') or {}
    return RuntimeConfig(
        ollama=OllamaSettings(
            base_url=str(oll.get('base_url','')).strip(),
            timeout_sec=int(oll.get('timeout_sec',420)),
            think=oll.get('think', False),
            temperature=float(oll.get('temperature',0.0)),
            num_ctx=int(oll.get('num_ctx',4096)),
            num_predict=int(oll.get('num_predict',400)),
            keep_alive=oll.get('keep_alive',0),
            options=oll.get('options',{}) if isinstance(oll.get('options',{}), dict) else {},
        ),
        models=ModelsSettings(
            planner_model=str(models_cfg.get('planner_model', cg.get('planner_model','qwen3:14b-q4_K_M'))),
            coder_model=str(models_cfg.get('coder_model', cg.get('coder_model','qwen2.5-coder:14b-instruct-q4_K_M'))),
            test_generator_model=str(models_cfg.get('test_generator_model', generation_cfg.get('test_generator_model', 'qwen2.5-coder:7b-instruct'))),
            repair_model=str(models_cfg.get('repair_model', generation_cfg.get('repair_model', models_cfg.get('coder_model', cg.get('coder_model','qwen2.5-coder:14b-instruct-q4_K_M'))))),
        ),
        prompts=PromptSettings(**{k:str(prompts_cfg.get(k,'')) for k in ['system_rules','planner_user_template','coder_user_template','repair_user_template','test_generator_user_template','test_generator_example']}),
        defaults_constraints=[str(x) for x in defaults.get('constraints',[])],
        repair_enabled=bool(generation_cfg.get('repair_enabled', True)),
        max_repair_attempts=int(generation_cfg.get('max_repair_attempts',1)),
        test_generation_mode=str(generation_cfg.get('test_generation_mode', 'always' if cg.get('generate_tests_by_default', True) else 'if_missing')),
        test_generator_max_example_tests=int(generation_cfg.get('test_generator_max_example_tests',1)),
        trace=TraceSettings(
            save_to_file=bool(trace.get('save_to_file',True)),
            show_prompts=bool(trace.get('show_prompts',True)),
            show_raw_llm_output=bool(trace.get('show_raw_llm_output',True)),
            output_dir=str(trace.get('output_dir', cg.get('traces_dir','runs'))),
        ),
        config_path=str(path),
    )

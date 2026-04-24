from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from codegenerator.logger import get_logger

LOGGER = get_logger(__name__)

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"


@dataclass(slots=True)
class OllamaSettings:
    base_url: str
    api_key: str | None
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
    test_planner_user_template: str


@dataclass(slots=True)
class TraceSettings:
    save_to_file: bool
    show_prompts: bool
    show_raw_llm_output: bool
    output_dir: str

@dataclass(slots=True)
class PromptBudgetSettings:
    generate_chars_limit: int
    generate_test_chars_limit: int
    repair_chars_limit: int
    min_user_prompt_chars: int
    user_prompt_reserve_chars: int


@dataclass(slots=True)
class BudgetStrategySettings:
    generate_module_outline_keep: int
    generate_related_tests_keep: int
    generate_related_test_source_limit: int
    generate_target_source_limit: int
    generate_test_drop_reference: bool
    generate_test_module_outline_keep: int
    generate_test_related_tests_keep: int
    generate_test_related_test_source_limit: int
    generate_test_target_source_limit: int
    repair_drop_reference: bool
    repair_module_outline_keep: int
    repair_verification_message_limit: int
    repair_previous_artifact_code_limit: int
    repair_related_tests_keep: int
    repair_related_test_source_limit: int
    repair_target_source_limit: int


@dataclass(slots=True)
class PromptAssemblySettings:
    coder_related_tests_max_items: int
    coder_related_tests_per_item_chars: int
    coder_soft_module_outline_chars: int
    coder_runtime_request_chars: int
    coder_runtime_target_chars: int
    coder_runtime_module_outline_chars: int
    coder_runtime_related_tests_min_chars: int
    repair_target_source_chars: int
    repair_previous_code_chars: int
    repair_full_file_source_chars: int
    test_example_chars: int
    test_example_trim_chars: int
    test_target_trim_first_chars: int
    test_target_trim_second_chars: int
    test_request_trim_first_chars: int
    test_request_trim_second_chars: int
    test_related_tests_trim_min_chars: int
    test_example_trim_second_chars: int
    test_target_trim_final_chars: int
    test_example_trim_final_chars: int


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
    coder_prompt_target_chars: int
    coder_prompt_hard_limit: int
    coder_max_reference_artifacts: int
    coder_max_reference_chars: int
    coder_max_full_file_chars: int
    repair_prompt_hard_limit: int
    repair_max_reference_chars: int
    trace: TraceSettings
    prompt_budget: PromptBudgetSettings
    budget_strategy: BudgetStrategySettings
    prompt_assembly: PromptAssemblySettings
    config_path: str


def _load_yaml_config(file_path: Path) -> dict[str, Any]:
    if not file_path.exists():
        LOGGER.warning('Config file not found at %s, using empty config.', file_path)
        return {}
    with file_path.open('r', encoding='utf-8') as handle:
        payload = yaml.safe_load(handle) or {}
        return payload if isinstance(payload, dict) else {}


def _cast_type(value: str, desired_type: type[Any]) -> Any:
    try:
        if desired_type is bool:
            return value.lower() in ('1', 'true', 'yes', 'on')
        if desired_type is int:
            return int(value)
        if desired_type is float:
            return float(value)
        if desired_type is list:
            return yaml.safe_load(value)
        return value
    except Exception as exc:
        LOGGER.warning('Could not cast value to %s: %s', desired_type, exc)
        return value


def _apply_env_overrides(config: dict[str, Any], prefix: str = '') -> dict[str, Any]:
    for key, value in list(config.items()):
        full_key = f'{prefix}__{key}'.upper() if prefix else key.upper()
        if isinstance(value, dict):
            config[key] = _apply_env_overrides(value, full_key)
            continue
        env_value = os.getenv(full_key)
        if env_value is not None:
            LOGGER.debug('Overriding %s from env', full_key)
            config[key] = _cast_type(env_value, type(value))
    return config


def _guess_type(value: str) -> Any:
    try:
        return yaml.safe_load(value)
    except Exception:
        return value


def _inject_dynamic_env_vars(config: dict[str, Any], prefix: str = 'RS__') -> dict[str, Any]:
    for env_key, raw_val in os.environ.items():
        if not env_key.startswith(prefix):
            continue
        parts = [item for item in env_key[len(prefix):].split('__') if item]
        if not parts:
            continue
        cursor = config
        for part in parts[:-1]:
            lower_part = part.lower()
            matched = next((k for k in cursor.keys() if k.lower() == lower_part), None)
            if matched is None:
                matched = lower_part
                cursor[matched] = {}
            elif not isinstance(cursor[matched], dict):
                LOGGER.warning("Converting '%s' to object to inject subkeys for env %s", matched, env_key)
                cursor[matched] = {}
            cursor = cursor[matched]
        last = parts[-1].lower()
        existing = next((k for k in cursor.keys() if k.lower() == last), None)
        if existing is None:
            cursor[last] = _guess_type(raw_val)
            LOGGER.debug('Injected %s from env', env_key)
    return config


def _merge_config(path: Path) -> dict[str, Any]:
    payload = _load_yaml_config(path)
    payload = _apply_env_overrides(payload, 'RS')
    payload = _inject_dynamic_env_vars(payload)
    return payload


def load_config(config_path: str | Path | None = None) -> RuntimeConfig:
    path = Path(config_path or DEFAULT_CONFIG_PATH).resolve()
    data = _merge_config(path)
    llm = data.get('llm') or {}
    oll = llm.get('ollama') or {}
    ollama_api_key = oll.get('api_key', os.environ.get('OLLAMA_API_KEY'))
    if ollama_api_key is not None:
        ollama_api_key = str(ollama_api_key).strip() or None
    cg = data.get('codegenerator') or {}
    prompts_cfg = cg.get('prompts') or {}
    models_cfg = cg.get('models') or {}
    generation_cfg = cg.get('generation') or {}
    defaults_cfg = cg.get('defaults') or {}
    trace_cfg = cg.get('trace') or {}
    prompt_budget_cfg = cg.get('prompt_budget') or {}
    budget_strategy_cfg = cg.get('budget_strategy') or {}
    prompt_assembly_cfg = cg.get('prompt_assembly') or {}
    return RuntimeConfig(
        ollama=OllamaSettings(
            base_url=str(oll.get('base_url', '')).strip(),
            api_key=ollama_api_key,
            timeout_sec=int(oll.get('timeout_sec', 420)),
            think=oll.get('think', False),
            temperature=float(oll.get('temperature', 0.0)),
            num_ctx=int(oll.get('num_ctx', 4096)),
            num_predict=int(oll.get('num_predict', 400)),
            keep_alive=oll.get('keep_alive', 0),
            options=oll.get('options', {}) if isinstance(oll.get('options', {}), dict) else {},
        ),
        models=ModelsSettings(
            planner_model=str(models_cfg.get('planner_model', 'qwen3:14b-q4_K_M')),
            coder_model=str(models_cfg.get('coder_model', 'qwen2.5-coder:14b-instruct-q4_K_M')),
            test_generator_model=str(models_cfg.get('test_generator_model', 'qwen2.5-coder:7b-instruct')),
            repair_model=str(models_cfg.get('repair_model', models_cfg.get('coder_model', 'qwen2.5-coder:14b-instruct-q4_K_M'))),
        ),
        prompts=PromptSettings(**{key: str(prompts_cfg.get(key, '')) for key in ['system_rules', 'planner_user_template', 'coder_user_template', 'repair_user_template', 'test_generator_user_template', 'test_generator_example', 'test_planner_user_template']}),
        defaults_constraints=[str(item) for item in defaults_cfg.get('constraints', [])],
        repair_enabled=bool(generation_cfg.get('repair_enabled', True)),
        max_repair_attempts=int(generation_cfg.get('max_repair_attempts', 1)),
        test_generation_mode=str(generation_cfg.get('test_generation_mode', 'always')),
        test_generator_max_example_tests=int(generation_cfg.get('test_generator_max_example_tests', 1)),
        coder_prompt_target_chars=int(generation_cfg.get('coder_prompt_target_chars', 5000)),
        coder_prompt_hard_limit=int(generation_cfg.get('coder_prompt_hard_limit', 5400)),
        coder_max_reference_artifacts=int(generation_cfg.get('coder_max_reference_artifacts', 1)),
        coder_max_reference_chars=int(generation_cfg.get('coder_max_reference_chars', 650)),
        coder_max_full_file_chars=int(generation_cfg.get('coder_max_full_file_chars', 0)),
        repair_prompt_hard_limit=int(generation_cfg.get('repair_prompt_hard_limit', 5750)),
        repair_max_reference_chars=int(generation_cfg.get('repair_max_reference_chars', 420)),
        trace=TraceSettings(
            save_to_file=bool(trace_cfg.get('save_to_file', True)),
            show_prompts=bool(trace_cfg.get('show_prompts', True)),
            show_raw_llm_output=bool(trace_cfg.get('show_raw_llm_output', True)),
            output_dir=str(trace_cfg.get('output_dir', 'runs')),
        ),
        prompt_budget=PromptBudgetSettings(
            generate_chars_limit=int(prompt_budget_cfg.get('generate_chars_limit', 5600)),
            generate_test_chars_limit=int(prompt_budget_cfg.get('generate_test_chars_limit', 5400)),
            repair_chars_limit=int(prompt_budget_cfg.get('repair_chars_limit', 5600)),
            min_user_prompt_chars=int(prompt_budget_cfg.get('min_user_prompt_chars', 400)),
            user_prompt_reserve_chars=int(prompt_budget_cfg.get('user_prompt_reserve_chars', 100)),
        ),
        budget_strategy=BudgetStrategySettings(
            generate_module_outline_keep=int(budget_strategy_cfg.get('generate_module_outline_keep', 4)),
            generate_related_tests_keep=int(budget_strategy_cfg.get('generate_related_tests_keep', 1)),
            generate_related_test_source_limit=int(budget_strategy_cfg.get('generate_related_test_source_limit', 450)),
            generate_target_source_limit=int(budget_strategy_cfg.get('generate_target_source_limit', 1400)),
            generate_test_drop_reference=bool(budget_strategy_cfg.get('generate_test_drop_reference', True)),
            generate_test_module_outline_keep=int(budget_strategy_cfg.get('generate_test_module_outline_keep', 2)),
            generate_test_related_tests_keep=int(budget_strategy_cfg.get('generate_test_related_tests_keep', 1)),
            generate_test_related_test_source_limit=int(budget_strategy_cfg.get('generate_test_related_test_source_limit', 500)),
            generate_test_target_source_limit=int(budget_strategy_cfg.get('generate_test_target_source_limit', 1400)),
            repair_drop_reference=bool(budget_strategy_cfg.get('repair_drop_reference', True)),
            repair_module_outline_keep=int(budget_strategy_cfg.get('repair_module_outline_keep', 2)),
            repair_verification_message_limit=int(budget_strategy_cfg.get('repair_verification_message_limit', 300)),
            repair_previous_artifact_code_limit=int(budget_strategy_cfg.get('repair_previous_artifact_code_limit', 1200)),
            repair_related_tests_keep=int(budget_strategy_cfg.get('repair_related_tests_keep', 1)),
            repair_related_test_source_limit=int(budget_strategy_cfg.get('repair_related_test_source_limit', 450)),
            repair_target_source_limit=int(budget_strategy_cfg.get('repair_target_source_limit', 900)),
        ),
        prompt_assembly=PromptAssemblySettings(
            coder_related_tests_max_items=int(prompt_assembly_cfg.get('coder_related_tests_max_items', 1)),
            coder_related_tests_per_item_chars=int(prompt_assembly_cfg.get('coder_related_tests_per_item_chars', 500)),
            coder_soft_module_outline_chars=int(prompt_assembly_cfg.get('coder_soft_module_outline_chars', 400)),
            coder_runtime_request_chars=int(prompt_assembly_cfg.get('coder_runtime_request_chars', 220)),
            coder_runtime_target_chars=int(prompt_assembly_cfg.get('coder_runtime_target_chars', 220)),
            coder_runtime_module_outline_chars=int(prompt_assembly_cfg.get('coder_runtime_module_outline_chars', 120)),
            coder_runtime_related_tests_min_chars=int(prompt_assembly_cfg.get('coder_runtime_related_tests_min_chars', 180)),
            repair_target_source_chars=int(prompt_assembly_cfg.get('repair_target_source_chars', 900)),
            repair_previous_code_chars=int(prompt_assembly_cfg.get('repair_previous_code_chars', 1200)),
            repair_full_file_source_chars=int(prompt_assembly_cfg.get('repair_full_file_source_chars', 700)),
            test_example_chars=int(prompt_assembly_cfg.get('test_example_chars', 900)),
            test_example_trim_chars=int(prompt_assembly_cfg.get('test_example_trim_chars', 520)),
            test_target_trim_first_chars=int(prompt_assembly_cfg.get('test_target_trim_first_chars', 1100)),
            test_target_trim_second_chars=int(prompt_assembly_cfg.get('test_target_trim_second_chars', 800)),
            test_request_trim_first_chars=int(prompt_assembly_cfg.get('test_request_trim_first_chars', 420)),
            test_request_trim_second_chars=int(prompt_assembly_cfg.get('test_request_trim_second_chars', 220)),
            test_related_tests_trim_min_chars=int(prompt_assembly_cfg.get('test_related_tests_trim_min_chars', 220)),
            test_example_trim_second_chars=int(prompt_assembly_cfg.get('test_example_trim_second_chars', 320)),
            test_target_trim_final_chars=int(prompt_assembly_cfg.get('test_target_trim_final_chars', 520)),
            test_example_trim_final_chars=int(prompt_assembly_cfg.get('test_example_trim_final_chars', 160)),
        ),
        config_path=str(path),
    )

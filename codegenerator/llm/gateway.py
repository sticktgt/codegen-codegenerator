from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from codegenerator.config import RuntimeConfig
from codegenerator.llm.ollama_client import OllamaClient, OllamaCallResult
from codegenerator.logger import get_logger
logger = get_logger('codegenerator.gateway')

@dataclass(slots=True)
class CallMeta:
    step: str
    model: str
    prompt_chars: int
    system_chars: int
    user_chars: int

def create_client(config: RuntimeConfig) -> OllamaClient:
    return OllamaClient(
        base_url=config.ollama.base_url,
        timeout_sec=config.ollama.timeout_sec,
        api_key=config.ollama.api_key,
    )

def call_model(*, client: OllamaClient, model: str, system_prompt: str, user_prompt: str, think: bool | None, config: RuntimeConfig, step: str) -> tuple[OllamaCallResult, CallMeta]:
    meta = CallMeta(step=step, model=model, prompt_chars=len(system_prompt)+len(user_prompt), system_chars=len(system_prompt), user_chars=len(user_prompt))
    logger.info('%s call: model=%s prompt_chars=%s system_chars=%s user_chars=%s', step, model, meta.prompt_chars, meta.system_chars, meta.user_chars)
    result = client.chat(model=model, messages=[{'role':'system','content':system_prompt},{'role':'user','content':user_prompt}], think=think, temperature=config.ollama.temperature, num_ctx=config.ollama.num_ctx, num_predict=config.ollama.num_predict, keep_alive=config.ollama.keep_alive, fmt='json', extra_options=config.ollama.options)
    chars_per_token = round(meta.prompt_chars / result.prompt_tokens, 3) if result.prompt_tokens else None
    logger.info('%s result: done=%s reason=%s prompt_tokens=%s output_tokens=%s total_tokens=%s chars_per_token=%s duration=%.2fs', step, result.done, result.done_reason, result.prompt_tokens, result.output_tokens, (result.prompt_tokens or 0) + (result.output_tokens or 0), chars_per_token if chars_per_token is not None else 'n/a', result.duration_sec)
    return result, meta

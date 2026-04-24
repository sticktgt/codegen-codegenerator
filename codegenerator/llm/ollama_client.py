# llm/ollama_client.py
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional
import time
import requests

from codegenerator.logger import get_logger

logger = get_logger()


@dataclass
class OllamaCallResult:
    content: str
    raw: Dict[str, Any]
    prompt_tokens: int
    output_tokens: int
    done: bool
    done_reason: str
    duration_sec: float
    total_duration_sec: float
    load_duration_sec: float
    prompt_eval_duration_sec: float
    eval_duration_sec: float

    def usage_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload.pop('content', None)
        payload.pop('raw', None)
        payload.pop('done', None)
        payload.pop('done_reason', None)
        payload['total_tokens'] = self.prompt_tokens + self.output_tokens
        return payload


class OllamaClient:
    def __init__(
        self,
        base_url: str,
        timeout_sec: int = 180,
        api_key: str | None = None,
    ):
        normalized_base_url = base_url.rstrip('/')

        if normalized_base_url.endswith('/api'):
            self.api_base_url = normalized_base_url
            self.base_url = normalized_base_url[:-4]
        else:
            self.base_url = normalized_base_url
            self.api_base_url = f'{normalized_base_url}/api'

        self.chat_url = f'{self.api_base_url}/chat'
        self.timeout_sec = timeout_sec
        self.api_key = (api_key or '').strip() or None
        self.session = requests.Session()

    def chat(
        self,
        model: str,
        messages: List[Dict[str, str]],
        *,
        think: Optional[bool] = None,
        temperature: float = 0.0,
        num_ctx: Optional[int] = None,
        num_predict: int = 600,
        keep_alive: int | str = 0,
        stream: bool = False,
        fmt: Optional[Any] = None,  # "json" or JSON schema dict (optional)
        extra_options: Optional[Dict[str, Any]] = None,
    ) -> OllamaCallResult:
        options: Dict[str, Any] = {
            "temperature": temperature,
            "num_predict": num_predict,
        }
        if num_ctx is not None:
            options["num_ctx"] = num_ctx

        if extra_options:
            # allow yaml-driven tuning: num_thread, num_batch, use_mmap, repeat_penalty, etc.
            options.update(extra_options)

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "keep_alive": keep_alive,
            "options": options,
        }

        # qwen3:* should typically use think=False for tool-ish tasks
        if think is not None:
            payload["think"] = think

        if fmt is not None:
            payload["format"] = fmt

        t0 = time.time()
        try:
            # r = self.session.post(self.chat_url, json=payload, timeout=self.timeout_sec)
            headers: Dict[str, str] = {}
            if self.api_key:
                headers['Authorization'] = f'Bearer {self.api_key}'

            r = self.session.post(
                self.chat_url,
                json=payload,
                headers=headers or None,
                timeout=self.timeout_sec,
            )

            if not r.ok:
                logger.error("Ollama HTTP %s body: %s", r.status_code, (r.text or "")[:2000])
                r.raise_for_status()
            
            data = r.json()

            total = data.get("total_duration", 0)
            load = data.get("load_duration", 0)
            pe = data.get("prompt_eval_duration", 0)
            ev = data.get("eval_duration", 0)
            pc = data.get("prompt_eval_count", 0)
            ec = data.get("eval_count", 0)

            # token/s (как в документации Ollama: eval_count / eval_duration * 1e9) :contentReference[oaicite:1]{index=1}
            tps = (ec / ev * 1e9) if ev else 0.0
            logger.info(
                "ollama usage prompt_tokens=%s output_tokens=%s total_tokens=%s total=%.2fs load=%.2fs prompt=%.2fs eval=%.2fs tok/s=%.2f",
                pc,
                ec,
                int(pc) + int(ec),
                total / 1e9,
                load / 1e9,
                pe / 1e9,
                ev / 1e9,
                tps,
            )

        except requests.RequestException as e:
            logger.exception("Ollama request failed")
            raise RuntimeError(f"Ollama request failed: {e}") from e
        except ValueError as e:
            logger.exception("Invalid JSON from Ollama")
            raise RuntimeError(f"Ollama returned invalid JSON: {e}") from e
        finally:
            t1 = time.time()

        msg = data.get("message") or {}
        content = msg.get("content", "")

        return OllamaCallResult(
            content=content,
            raw=data,
            prompt_tokens=int(data.get("prompt_eval_count", 0)),
            output_tokens=int(data.get("eval_count", 0)),
            done=bool(data.get("done", True)),
            done_reason=str(data.get("done_reason", "")),
            duration_sec=(t1 - t0),
            total_duration_sec=float(data.get("total_duration", 0)) / 1e9,
            load_duration_sec=float(data.get("load_duration", 0)) / 1e9,
            prompt_eval_duration_sec=float(data.get("prompt_eval_duration", 0)) / 1e9,
            eval_duration_sec=float(data.get("eval_duration", 0)) / 1e9,
        )
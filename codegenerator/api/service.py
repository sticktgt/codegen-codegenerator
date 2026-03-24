from __future__ import annotations
import json
from pathlib import Path
from typing import Any
import yaml
from codegenerator.logger import get_logger
from codegenerator.models.requests import GenerationRequest, RepairRequest
from codegenerator.orchestration.generation_service import generate, repair, generate_test

logger = get_logger("codegenerator.api")


def _load_request(path: str | Path) -> dict[str, Any]:
    request_path = Path(path)
    text = request_path.read_text(encoding="utf-8")
    suffix = request_path.suffix.lower()
    try:
        if suffix in {".yaml", ".yml"}:
            data = yaml.safe_load(text)
            if not isinstance(data, dict):
                raise ValueError("YAML request must contain an object at top level")
            return data
        return json.loads(text)
    except json.JSONDecodeError as exc:
        logger.error("Invalid JSON in request file %s at line=%s col=%s pos=%s", request_path, exc.lineno, exc.colno, exc.pos)
        raise ValueError(
            f"Invalid JSON in request file {request_path}: line {exc.lineno}, column {exc.colno}. "
            "For multiline code snippets use escaped newlines (\n) or provide the request as YAML."
        ) from exc
    except yaml.YAMLError as exc:
        logger.error("Invalid YAML in request file %s: %s", request_path, exc)
        raise ValueError(f"Invalid YAML in request file {request_path}: {exc}") from exc


def generate_from_file(request_file: str | Path, config_path: str) -> dict:
    payload = _load_request(request_file)
    req = GenerationRequest(**payload)
    return generate(req, config_path).to_dict()


def repair_from_file(request_file: str | Path, config_path: str) -> dict:
    payload = _load_request(request_file)
    req = RepairRequest(**payload)
    return repair(req, config_path).to_dict()


def generate_test_from_file(request_file: str | Path, config_path: str) -> dict:
    payload = _load_request(request_file)
    req = GenerationRequest(**payload)
    return generate_test(req, config_path).to_dict()

from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from typing import Any

def build_trace_dir(project_root: str | Path = '.') -> Path:
    runs_dir = Path(project_root)
    runs_dir.mkdir(parents=True, exist_ok=True)
    return runs_dir

def build_trace_path(project_root: str | Path, request_id: str) -> Path:
    runs_dir = build_trace_dir(project_root)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    return runs_dir / f"{timestamp}_{request_id}.json"

def save_trace(trace_path: str | Path, trace: dict[str, Any]) -> None:
    path = Path(trace_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding='utf-8')

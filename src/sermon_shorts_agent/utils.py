import json
import re
from pathlib import Path


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def format_ts(seconds: float) -> str:
    total = max(0, int(seconds))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def sanitize_slug(text: str) -> str:
    text = re.sub(r'[^0-9A-Za-z가-힣]+', '-', text.strip())
    text = re.sub(r'-+', '-', text).strip('-')
    return text or 'clip'


def sentence_chunks(text: str):
    parts = re.split(r'(?<=[.!?。！？])\s+|\n+', text.strip())
    return [p.strip() for p in parts if p.strip()]

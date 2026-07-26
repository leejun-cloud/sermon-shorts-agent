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


def format_vtt_ts(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def sanitize_slug(text: str) -> str:
    text = re.sub(r'[^0-9A-Za-z가-힣]+', '-', text.strip())
    text = re.sub(r'-+', '-', text).strip('-')
    return text or 'clip'


def sentence_chunks(text: str):
    parts = re.split(r'(?<=[.!?。！？])\s+|\n+', text.strip())
    return [p.strip() for p in parts if p.strip()]


def write_webvtt(path: Path, segments) -> None:
    lines = ['WEBVTT', '']
    for idx, seg in enumerate(segments, start=1):
        lines += [
            str(idx),
            f"{format_vtt_ts(seg.start)} --> {format_vtt_ts(seg.end)}",
            seg.text.strip(),
            ''
        ]
    path.write_text('\n'.join(lines), encoding='utf-8')

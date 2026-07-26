import re
from pathlib import Path
from typing import List

from .models import Segment, Highlight
from .utils import read_json


def _coerce_segments(items) -> List[Segment]:
    segments = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            start = float(item['start'])
            end = float(item['end'])
            text = str(item['text']).strip()
        except Exception:
            continue
        if start < end and text:
            segments.append(Segment(start=start, end=end, text=text))
    return sorted(segments, key=lambda s: (s.start, s.end))


def load_transcript(path: Path) -> List[Segment]:
    if path.suffix.lower() == '.json':
        data = read_json(path)
        if isinstance(data, dict) and isinstance(data.get('segments'), list):
            data = data['segments']
        if not isinstance(data, list):
            raise ValueError(f'invalid transcript json: {path}')
        segments = _coerce_segments(data)
        if not segments:
            raise ValueError(f'no valid segments in transcript: {path}')
        return segments
    if path.suffix.lower() == '.srt':
        return load_srt(path)
    raise ValueError(f'unsupported transcript file: {path}')


def load_highlights(path: Path) -> List[Highlight]:
    if not path or not path.exists():
        return []
    data = read_json(path)
    highlights = []
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                start = float(item['start'])
                end = float(item['end'])
            except Exception:
                continue
            if start >= end:
                continue
            highlights.append(Highlight(
                start=start,
                end=end,
                score=float(item.get('score', 0.0) or 0.0),
                peak_db=float(item.get('peak_db', 0.0) or 0.0),
            ))
    return sorted(highlights, key=lambda h: (h.start, h.end))


def load_srt(path: Path) -> List[Segment]:
    text = path.read_text(encoding='utf-8')
    blocks = re.split(r'\n\s*\n', text.strip())
    segments = []
    for block in blocks:
        lines = [ln.strip('\ufeff') for ln in block.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        if '-->' in lines[0]:
            timing = lines[0]
            payload = lines[1:]
        else:
            timing = lines[1] if len(lines) > 1 else ''
            payload = lines[2:]
        if '-->' not in timing:
            continue
        start_s, end_s = [part.strip() for part in timing.split('-->')]
        start = _parse_srt_time(start_s)
        end = _parse_srt_time(end_s)
        body = ' '.join(payload).strip()
        if start < end and body:
            segments.append(Segment(start=start, end=end, text=body))
    if not segments:
        raise ValueError(f'no valid SRT segments: {path}')
    return segments


def _parse_srt_time(value: str) -> float:
    value = value.replace(',', '.')
    h, m, s = value.split(':')
    return int(h) * 3600 + int(m) * 60 + float(s)

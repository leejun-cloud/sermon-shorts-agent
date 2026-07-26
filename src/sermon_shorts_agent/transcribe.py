from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from .models import Segment
from .utils import write_json, write_webvtt


@lru_cache(maxsize=2)
def _model(model_size: str = 'tiny'):
    from faster_whisper import WhisperModel

    return WhisperModel(model_size, device='cpu', compute_type='int8')


def transcribe_video(
    video_path: Path,
    out_dir: Path,
    *,
    model_size: str = 'tiny',
    language: Optional[str] = None,
) -> List[Segment]:
    out_dir.mkdir(parents=True, exist_ok=True)
    model = _model(model_size)
    segments_iter, info = model.transcribe(
        str(video_path),
        language=language,
        vad_filter=True,
        beam_size=3,
        word_timestamps=False,
    )
    segments: List[Segment] = []
    for item in segments_iter:
        text = (item.text or '').strip()
        if not text:
            continue
        start = float(item.start)
        end = float(item.end)
        if end <= start:
            continue
        segments.append(Segment(start=start, end=end, text=text))
    if not segments:
        raise RuntimeError(f'no transcript generated for {video_path}')
    write_json(out_dir / 'transcript.json', [
        {'start': round(seg.start, 3), 'end': round(seg.end, 3), 'text': seg.text}
        for seg in segments
    ])
    write_webvtt(out_dir / 'transcript.vtt', segments)
    write_json(out_dir / 'transcript_meta.json', {
        'language': getattr(info, 'language', language),
        'language_probability': getattr(info, 'language_probability', None),
        'duration': getattr(info, 'duration', None),
        'model_size': model_size,
    })
    return segments

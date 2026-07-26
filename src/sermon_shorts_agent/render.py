import json
import subprocess
from pathlib import Path
from typing import Iterable, List, Optional

from .models import Candidate, Segment
from .utils import ensure_dir, sanitize_slug, write_json, write_webvtt


def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
    except ImportError as exc:
        raise RuntimeError('imageio-ffmpeg is required for rendering; pip install imageio-ffmpeg') from exc
    return imageio_ffmpeg.get_ffmpeg_exe()


def make_relative_srt(segments: Iterable[Segment], clip_start: float, out_path: Path) -> None:
    lines = []
    for idx, seg in enumerate(segments, start=1):
        start = max(0.0, seg.start - clip_start)
        end = max(start + 0.1, seg.end - clip_start)
        lines += [
            str(idx),
            f"{_srt_ts(start)} --> {_srt_ts(end)}",
            seg.text.strip(),
            ''
        ]
    out_path.write_text('\n'.join(lines), encoding='utf-8')


def make_relative_vtt(segments: Iterable[Segment], clip_start: float, out_path: Path) -> None:
    shifted = [
        Segment(
            start=max(0.0, seg.start - clip_start),
            end=max(max(0.0, seg.start - clip_start) + 0.1, seg.end - clip_start),
            text=seg.text,
        )
        for seg in segments
    ]
    write_webvtt(out_path, shifted)


def _srt_ts(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def load_candidates(path: Path) -> List[Candidate]:
    raw = json.loads(path.read_text(encoding='utf-8'))
    out = []
    for item in raw:
        segments = [Segment(**seg) for seg in item.get('segments', [])]
        out.append(Candidate(
            rank=item['rank'], start=item['start'], end=item['end'], score=item['score'],
            category=item['category'], title=item['title'], summary=item['summary'],
            hook=item['hook'], transcript=item['transcript'], reasons=item.get('reasons', []),
            hashtags=item.get('hashtags', []), segments=segments
        ))
    return out


def _candidate_slug(candidate: Candidate) -> str:
    return f"{candidate.rank:02d}-{sanitize_slug(candidate.title)}"


def _render_clip(video_path: Path, mp4_path: Path, start: float, end: float, *, subtitles_vtt: Optional[Path] = None, burn_subtitles: bool = True) -> None:
    ffmpeg = ffmpeg_exe()
    vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
    if burn_subtitles and subtitles_vtt:
        safe_vtt = str(subtitles_vtt).replace('\\', '\\\\').replace(':', '\\:').replace("'", "\\'")
        vf = vf + f",subtitles='{safe_vtt}'"
    cmd = [
        ffmpeg, '-y', '-ss', str(start), '-to', str(end), '-i', str(video_path),
        '-vf', vf,
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
        '-c:a', 'aac', '-b:a', '128k',
        '-movflags', '+faststart',
        str(mp4_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f'ffmpeg render failed for {mp4_path.name}: {result.stderr}')


def extract_range(video_path: Path, out_dir: Path, *, start: float, end: float, title: str, segments: List[Segment], burn_subtitles: bool = True) -> dict:
    ensure_dir(out_dir)
    slug = sanitize_slug(title)
    mp4_path = out_dir / f'{slug}.mp4'
    srt_path = out_dir / f'{slug}.srt'
    vtt_path = out_dir / f'{slug}.vtt'
    clip_segments = [seg for seg in segments if seg.end >= start and seg.start <= end]
    make_relative_srt(clip_segments, start, srt_path)
    make_relative_vtt(clip_segments, start, vtt_path)
    _render_clip(video_path, mp4_path, start, end, subtitles_vtt=vtt_path, burn_subtitles=burn_subtitles)
    return {
        'video': str(mp4_path),
        'srt': str(srt_path),
        'vtt': str(vtt_path),
        'start': start,
        'end': end,
        'duration': round(end - start, 3),
        'title': title,
    }


def render_previews(video_path: Path, candidates_path: Path, out_dir: Path, top: int = 3) -> List[Path]:
    candidates = load_candidates(candidates_path)[:top]
    ensure_dir(out_dir)
    ffmpeg = ffmpeg_exe()
    rendered = []
    manifest = []
    for candidate in candidates:
        slug = _candidate_slug(candidate)
        audio_path = out_dir / f"{slug}.mp3"
        cmd = [
            ffmpeg, '-y', '-ss', str(candidate.start), '-to', str(candidate.end), '-i', str(video_path),
            '-vn', '-acodec', 'libmp3lame', '-b:a', '128k', str(audio_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f'ffmpeg preview failed for {candidate.title}: {result.stderr}')
        rendered.append(audio_path)
        manifest.append({
            'file': audio_path.name,
            'title': candidate.title,
            'category': candidate.category,
            'start': candidate.start,
            'end': candidate.end,
            'duration_s': round(candidate.end - candidate.start, 3),
            'hook': candidate.hook,
            'summary': candidate.summary,
            'reasons': candidate.reasons,
        })
    write_json(out_dir / 'preview_manifest.json', manifest)
    return rendered


def render_candidates(video_path: Path, candidates_path: Path, out_dir: Path, top: int = 3, burn_subtitles: bool = True) -> List[Path]:
    candidates = load_candidates(candidates_path)[:top]
    ensure_dir(out_dir)
    rendered = []
    manifest = []
    for candidate in candidates:
        slug = _candidate_slug(candidate)
        srt_path = out_dir / f"{slug}.srt"
        vtt_path = out_dir / f"{slug}.vtt"
        mp4_path = out_dir / f"{slug}.mp4"
        make_relative_srt(candidate.segments, candidate.start, srt_path)
        make_relative_vtt(candidate.segments, candidate.start, vtt_path)
        _render_clip(video_path, mp4_path, candidate.start, candidate.end, subtitles_vtt=vtt_path, burn_subtitles=burn_subtitles)
        rendered.append(mp4_path)
        manifest.append({
            'file': mp4_path.name,
            'title': candidate.title,
            'hook': candidate.hook,
            'summary': candidate.summary,
            'hashtags': candidate.hashtags,
            'start': candidate.start,
            'end': candidate.end,
            'duration_s': round(candidate.end - candidate.start, 3),
            'suggested_description': f"{candidate.summary}\n\n{' '.join(candidate.hashtags)}"
        })
    write_json(out_dir / 'upload_package.json', manifest)
    return rendered

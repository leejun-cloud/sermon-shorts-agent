import json
import subprocess
from pathlib import Path
from typing import Iterable, List

from .models import Candidate, Segment
from .utils import ensure_dir, sanitize_slug, write_json


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


def render_candidates(video_path: Path, candidates_path: Path, out_dir: Path, top: int = 3, burn_subtitles: bool = True) -> List[Path]:
    candidates = load_candidates(candidates_path)[:top]
    ensure_dir(out_dir)
    rendered = []
    ffmpeg = ffmpeg_exe()
    manifest = []
    for candidate in candidates:
        slug = f"{candidate.rank:02d}-{sanitize_slug(candidate.title)}"
        srt_path = out_dir / f"{slug}.srt"
        mp4_path = out_dir / f"{slug}.mp4"
        make_relative_srt(candidate.segments, candidate.start, srt_path)
        vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
        if burn_subtitles:
            safe_srt = str(srt_path).replace('\\', '\\\\').replace(':', '\\:').replace("'", "\\'")
            vf = vf + f",subtitles='{safe_srt}'"
        cmd = [
            ffmpeg, '-y', '-ss', str(candidate.start), '-to', str(candidate.end), '-i', str(video_path),
            '-vf', vf,
            '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
            '-c:a', 'aac', '-b:a', '128k',
            '-movflags', '+faststart',
            str(mp4_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f'ffmpeg render failed for {candidate.title}: {result.stderr}')
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

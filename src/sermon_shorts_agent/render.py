import json
import re
import subprocess
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from .models import Candidate, Segment
from .utils import ensure_dir, sanitize_slug, write_json, write_webvtt

CANVAS_W = 1080
CANVAS_H = 1920
# 레터박스 밴드(위+아래 합산)가 이 픽셀보다 작으면 원본이 이미 세로에 가깝다고 보고
# 크롭(확대) 방식으로 자동 폴백한다 — 자막 넣을 여백이 사실상 없기 때문.
MIN_USABLE_BAND_PX = 140


def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
    except ImportError as exc:
        raise RuntimeError('imageio-ffmpeg is required for rendering; pip install imageio-ffmpeg') from exc
    return imageio_ffmpeg.get_ffmpeg_exe()


def probe_video_size(video_path: Path) -> Optional[Tuple[int, int]]:
    """ffmpeg -i 출력에서 'Video: ... WxH'를 파싱해 원본 해상도를 얻는다.
    실패하면 None을 반환하고 호출부는 크롭 방식으로 폴백한다."""
    ffmpeg = ffmpeg_exe()
    result = subprocess.run(
        [ffmpeg, '-i', str(video_path)],
        capture_output=True, text=True
    )
    match = re.search(r'Video:.*?(\d{2,5})x(\d{2,5})', result.stderr)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _crop_fill_filter() -> str:
    return f"scale={CANVAS_W}:{CANVAS_H}:force_original_aspect_ratio=increase,crop={CANVAS_W}:{CANVAS_H}"


def _letterbox_blur_filter(fg_h: int) -> str:
    """원본을 자르지 않고 축소해 중앙에 놓고, 위아래 남는 여백은 같은 영상을
    확대+블러한 배경으로 채운다. 자막은 이 여백 밴드 안에 배치되므로
    원본 프레임(과 그 안에 이미 있는 자막/문구 카드)과 겹치지 않는다."""
    return (
        f"[0:v]split=2[bg][fg];"
        f"[bg]scale={CANVAS_W}:{CANVAS_H}:force_original_aspect_ratio=increase,"
        f"crop={CANVAS_W}:{CANVAS_H},boxblur=24:2,eq=brightness=-0.05[bgblur];"
        f"[fg]scale={CANVAS_W}:{fg_h}[fgscaled];"
        f"[bgblur][fgscaled]overlay=(W-w)/2:(H-h)/2[merged]"
    )


def resolve_layout(video_path: Path, layout: str) -> Tuple[str, Optional[int], Optional[int]]:
    """layout: 'crop' | 'letterbox' | 'auto'.
    반환: (실제 적용 레이아웃, 자막 MarginV, 전경 높이 fg_h) — crop이면 뒤 둘은 None."""
    if layout == 'crop':
        return 'crop', None, None
    size = probe_video_size(video_path)
    if not size:
        return 'crop', None, None  # 해상도 확인 실패 시 안전하게 기존 크롭 방식으로
    src_w, src_h = size
    fg_h = int(round(src_h * CANVAS_W / src_w))
    if fg_h % 2:
        fg_h -= 1
    fg_h = min(fg_h, CANVAS_H)
    band = (CANVAS_H - fg_h) // 2
    if layout == 'letterbox' or (layout == 'auto' and band * 2 >= MIN_USABLE_BAND_PX):
        margin_v = max(40, int(band * 0.35))
        return 'letterbox', margin_v, fg_h
    return 'crop', None, None


def _deoverlap(segments: Iterable[Segment]) -> List[Segment]:
    """ASR 세그먼트는 서로 몇 초씩 겹치는 경우가 흔하다(예: 0~4.16s, 1.72~6.48s).
    겹친 채로 자막을 구우면 두 줄이 동시에 떠서 libass가 충돌 방지를 위해
    한쪽을 위로 밀어버려(자동 stacking) 자막 위치가 들쭉날쭉해진다.
    각 구간의 끝을 다음 구간 시작 전까지로 잘라 항상 한 번에 한 줄만 보이게 한다."""
    items = list(segments)
    result = []
    for i, seg in enumerate(items):
        end = seg.end
        if i + 1 < len(items) and items[i + 1].start > seg.start:
            end = min(end, items[i + 1].start)
        end = max(end, seg.start + 0.1)
        result.append(Segment(start=seg.start, end=end, text=seg.text))
    return result


def make_relative_srt(segments: Iterable[Segment], clip_start: float, out_path: Path) -> None:
    lines = []
    for idx, seg in enumerate(_deoverlap(segments), start=1):
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
        for seg in _deoverlap(segments)
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


def _subtitle_filter_arg(subtitles_vtt: Path, margin_v: Optional[int]) -> str:
    safe_vtt = str(subtitles_vtt).replace('\\', '\\\\').replace(':', '\\:').replace("'", "\\'")
    if margin_v is None:
        return f"subtitles='{safe_vtt}'"
    # 이 환경의 ffmpeg/libass는 force_style의 Alignment을 무시하고 상단 기준으로
    # 앵커링한다(실측 확인됨) — Alignment 지정은 남겨두되 실제로는 no-op이다.
    # MarginV는 정상 동작해서 상단 여백 밴드 안쪽에 자막을 위치시키는 데는 문제없다.
    return f"subtitles='{safe_vtt}':force_style='Alignment=2,MarginV={margin_v}'"


def _render_clip(video_path: Path, mp4_path: Path, start: float, end: float, *,
                  subtitles_vtt: Optional[Path] = None, burn_subtitles: bool = True,
                  layout: str = 'auto') -> str:
    """layout: 'crop'(확대+크롭, 기존 방식) | 'letterbox'(원본 무손실 + 블러 배경,
    자막은 여백 밴드에) | 'auto'(원본 비율을 보고 자동 선택).
    반환값은 실제로 적용된 레이아웃('crop' 또는 'letterbox')."""
    ffmpeg = ffmpeg_exe()
    applied_layout, margin_v, fg_h = resolve_layout(video_path, layout)

    if applied_layout == 'letterbox':
        filter_complex = _letterbox_blur_filter(fg_h)
        if burn_subtitles and subtitles_vtt:
            filter_complex += f";[merged]{_subtitle_filter_arg(subtitles_vtt, margin_v)}[out]"
            map_label = '[out]'
        else:
            map_label = '[merged]'
        cmd = [
            ffmpeg, '-y', '-ss', str(start), '-to', str(end), '-i', str(video_path),
            '-filter_complex', filter_complex, '-map', map_label, '-map', '0:a?',
            '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
            '-c:a', 'aac', '-b:a', '128k',
            '-movflags', '+faststart',
            str(mp4_path)
        ]
    else:
        vf = _crop_fill_filter()
        if burn_subtitles and subtitles_vtt:
            vf = vf + ',' + _subtitle_filter_arg(subtitles_vtt, None)
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
    return applied_layout


def extract_range(video_path: Path, out_dir: Path, *, start: float, end: float, title: str, segments: List[Segment], burn_subtitles: bool = True, layout: str = 'auto') -> dict:
    ensure_dir(out_dir)
    slug = sanitize_slug(title)
    mp4_path = out_dir / f'{slug}.mp4'
    srt_path = out_dir / f'{slug}.srt'
    vtt_path = out_dir / f'{slug}.vtt'
    clip_segments = [seg for seg in segments if seg.end >= start and seg.start <= end]
    make_relative_srt(clip_segments, start, srt_path)
    make_relative_vtt(clip_segments, start, vtt_path)
    _render_clip(video_path, mp4_path, start, end, subtitles_vtt=vtt_path, burn_subtitles=burn_subtitles, layout=layout)
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


def render_candidates(video_path: Path, candidates_path: Path, out_dir: Path, top: int = 3, burn_subtitles: bool = True, layout: str = 'auto') -> List[Path]:
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
        applied_layout = _render_clip(video_path, mp4_path, candidate.start, candidate.end, subtitles_vtt=vtt_path, burn_subtitles=burn_subtitles, layout=layout)
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
            'layout': applied_layout,
            'suggested_description': f"{candidate.summary}\n\n{' '.join(candidate.hashtags)}"
        })
    write_json(out_dir / 'upload_package.json', manifest)
    return rendered

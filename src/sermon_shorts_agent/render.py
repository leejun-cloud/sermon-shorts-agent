import json
import math
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from .models import Candidate, Segment
from .utils import ensure_dir, sanitize_slug, write_json, write_webvtt

CANVAS_W = 1080
CANVAS_H = 1920
# 검은 밴드(letterbox) 레이아웃을 쓰려면 위/아래 각 밴드가 이 픽셀 이상이어야 한다.
# 제목(위)·자막(아래)을 밴드 안에 넣어야 하므로 여유 공간이 필요하다.
# 밴드가 이보다 작으면(원본이 이미 세로에 가까우면) 크롭 방식으로 폴백한다.
MIN_BAND_FOR_TEXT = 200


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


def _black_pad_filter(fg_h: int) -> str:
    """원본을 자르지 않고 폭에 맞춰 축소해 중앙에 놓고, 위아래 남는 공간은
    깔끔한 검은색으로 채운다(블러 아님). 제목은 위 검은 밴드, 자막은 아래
    검은 밴드에 놓여 원본 영상 위로 겹치지 않는다."""
    return (
        f"scale={CANVAS_W}:{fg_h},"
        f"pad={CANVAS_W}:{CANVAS_H}:(ow-iw)/2:(oh-ih)/2:color=black"
    )


def resolve_layout(video_path: Path, layout: str) -> Tuple[str, Optional[int], int, int]:
    """layout: 'crop' | 'pad'/'letterbox' | 'auto'.
    반환: (실제 적용 레이아웃, 전경 높이 fg_h, 위 밴드 높이, 아래 밴드 높이).
    crop이면 fg_h=None, 밴드=0."""
    if layout == 'crop':
        return 'crop', None, 0, 0
    size = probe_video_size(video_path)
    if not size:
        return 'crop', None, 0, 0  # 해상도 확인 실패 시 안전하게 크롭 방식으로
    src_w, src_h = size
    fg_h = int(round(src_h * CANVAS_W / src_w))
    if fg_h % 2:
        fg_h -= 1
    fg_h = min(fg_h, CANVAS_H)
    band = (CANVAS_H - fg_h) // 2
    if layout in ('pad', 'letterbox') or (layout == 'auto' and band >= MIN_BAND_FOR_TEXT):
        return 'pad', fg_h, band, band
    return 'crop', None, 0, 0


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


def _ass_ts(seconds: float) -> str:
    cs = max(0, int(round(seconds * 100)))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_escape(text: str) -> str:
    # ASS는 {}를 오버라이드 블록으로 해석하므로 치환하고, 줄바꿈은 공백으로 편다.
    return text.replace('{', '(').replace('}', ')').replace('\n', ' ').replace('\r', ' ').strip()


def _display_title(title: str) -> str:
    """카테고리 접두("핵심메시지 | ...")를 떼고 화면에 얹을 제목만 남긴다."""
    return title.split(' | ')[-1].strip() if title else ''


def _build_ass(title: Optional[str], segments: Optional[Iterable[Segment]], clip_start: float,
               duration: float, layout: str, top_band: int, bottom_band: int, out_path: Path) -> None:
    """제목(위)+자막(아래)을 담은 단일 ASS 자막 파일을 만든다. ASS는 자체 스타일에
    정의한 Alignment을 확실히 존중하므로(force_style 오버라이드의 한계가 없다)
    제목은 상단 중앙(\\an8), 자막은 하단 중앙(\\an2)에 안정적으로 배치된다."""
    title_text = _display_title(title or '')
    title_fs, sub_fs = 50, 46
    line_h_t, line_h_s = int(title_fs * 1.35), int(sub_fs * 1.35)
    if layout == 'pad':
        # 검은 밴드 안쪽에 세로 중앙 배치. 원본 영상 영역과 겹치지 않는다.
        t_lines = _est_lines(title_text, 18)
        title_mv = max(24, (top_band - t_lines * line_h_t) // 2)
        sub_mv = max(24, (bottom_band - 2 * line_h_s) // 2)
        outline = 2
    else:
        # crop 폴백: 영상 위에 얹으므로 가장자리 가까이 + 굵은 아웃라인.
        title_mv, sub_mv, outline = 70, 90, 4
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {CANVAS_W}\n"
        f"PlayResY: {CANVAS_H}\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Title,AppleSDGothicNeo,{title_fs},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
        f"1,0,0,0,100,100,0,0,1,{outline},0,8,60,60,{title_mv},1\n"
        f"Style: Sub,AppleSDGothicNeo,{sub_fs},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
        f"0,0,0,0,100,100,0,0,1,{outline},1,2,60,60,{sub_mv},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    events = []
    if title_text:
        events.append(f"Dialogue: 0,{_ass_ts(0)},{_ass_ts(duration)},Title,,0,0,0,,{_ass_escape(title_text)}")
    for seg in _deoverlap(list(segments or [])):
        s = max(0.0, seg.start - clip_start)
        if s >= duration:
            continue
        e = min(max(s + 0.1, seg.end - clip_start), duration)
        events.append(f"Dialogue: 0,{_ass_ts(s)},{_ass_ts(e)},Sub,,0,0,0,,{_ass_escape(seg.text)}")
    out_path.write_text(header + "\n".join(events) + "\n", encoding='utf-8')


def _est_lines(text: str, chars_per_line: int) -> int:
    return max(1, math.ceil(len(text) / chars_per_line)) if text else 1


def _render_clip(video_path: Path, mp4_path: Path, start: float, end: float, *,
                  title: Optional[str] = None, segments: Optional[List[Segment]] = None,
                  burn_subtitles: bool = True, layout: str = 'auto') -> str:
    """layout: 'crop'(확대+크롭) | 'pad'/'letterbox'(검은 레터박스, 제목 위·자막 아래)
    | 'auto'(원본 비율을 보고 자동). 반환값은 실제 적용된 레이아웃('crop' | 'pad')."""
    ffmpeg = ffmpeg_exe()
    applied_layout, fg_h, top_band, bottom_band = resolve_layout(video_path, layout)
    base_vf = _black_pad_filter(fg_h) if applied_layout == 'pad' else _crop_fill_filter()

    ass_path = None
    try:
        vf = base_vf
        if burn_subtitles:
            fd, tmp = tempfile.mkstemp(suffix='.ass')  # ASCII 경로 → subtitles 필터 이스케이프 안전
            os.close(fd)
            ass_path = Path(tmp)
            _build_ass(title, segments, start, end - start, applied_layout, top_band, bottom_band, ass_path)
            esc = str(ass_path).replace('\\', '\\\\').replace(':', '\\:').replace("'", "\\'")
            vf = base_vf + f",subtitles='{esc}'"
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
    finally:
        if ass_path and ass_path.exists():
            ass_path.unlink()
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
    _render_clip(video_path, mp4_path, start, end, title=title, segments=clip_segments,
                 burn_subtitles=burn_subtitles, layout=layout)
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
    # 자막 사이드카(srt/vtt)는 별도 폴더에 둔다. mp4 옆에 같은 이름으로 두면
    # 영상 플레이어가 자동 로드해 '구운 자막 + 플레이어 자막'이 이중으로 보인다.
    captions_dir = out_dir / 'captions'
    ensure_dir(captions_dir)
    rendered = []
    manifest = []
    for candidate in candidates:
        slug = _candidate_slug(candidate)
        srt_path = captions_dir / f"{slug}.srt"
        vtt_path = captions_dir / f"{slug}.vtt"
        mp4_path = out_dir / f"{slug}.mp4"
        make_relative_srt(candidate.segments, candidate.start, srt_path)
        make_relative_vtt(candidate.segments, candidate.start, vtt_path)
        applied_layout = _render_clip(video_path, mp4_path, candidate.start, candidate.end,
                                      title=candidate.title, segments=candidate.segments,
                                      burn_subtitles=burn_subtitles, layout=layout)
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

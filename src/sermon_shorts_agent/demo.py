from pathlib import Path
import subprocess

from .pipeline import analyze
from .render import ffmpeg_exe, render_candidates, render_previews
from .utils import ensure_dir, write_json


def build_demo(out_dir: Path) -> Path:
    ensure_dir(out_dir)
    transcript = [
        {"start": 0.0, "end": 7.0, "text": "오늘 우리는 왜 두려움이 우리를 붙잡는지 생각해 보겠습니다."},
        {"start": 7.0, "end": 15.0, "text": "그런데 하나님은 우리에게 두려워하지 말라고 말씀하십니다."},
        {"start": 15.0, "end": 24.0, "text": "문제보다 말씀이 더 큽니다. 이것이 오늘의 핵심 메시지입니다."},
        {"start": 24.0, "end": 33.0, "text": "여러분 지금 포기하고 싶다면, 반드시 말씀을 다시 붙잡아야 합니다!"},
        {"start": 33.0, "end": 42.0, "text": "누가복음 8장에서 예수님은 제자들의 두려움 한가운데 찾아오십니다."},
        {"start": 42.0, "end": 51.0, "text": "오늘 한 가지 실천이 필요합니다. 이번 주에 두려움의 이름 대신 말씀을 먼저 적으십시오."},
        {"start": 51.0, "end": 60.0, "text": "순종은 감정이 아니라 결단입니다. 하나님은 지금도 우리를 회복시키십니다."},
        {"start": 60.0, "end": 70.0, "text": "여러분 다시 일어나십시오. 은혜가 여러분을 살릴 것입니다!"}
    ]
    highlights = [
        {"start": 23.5, "end": 33.0, "score": 7.5, "peak_db": -3.0},
        {"start": 58.0, "end": 68.0, "score": 6.8, "peak_db": -4.1}
    ]
    transcript_path = out_dir / 'demo-transcript.json'
    highlights_path = out_dir / 'demo-highlights.json'
    write_json(transcript_path, transcript)
    write_json(highlights_path, highlights)
    video_path = out_dir / 'demo-video.mp4'
    _make_demo_video(video_path)
    analyze(transcript_path, highlights_path, out_dir, top_n=4)
    render_previews(video_path, out_dir / 'candidates.json', out_dir / 'previews', top=2)
    render_candidates(video_path, out_dir / 'candidates.json', out_dir / 'shorts', top=3)
    return out_dir


def _make_demo_video(video_path: Path) -> None:
    ffmpeg = ffmpeg_exe()
    cmd = [
        ffmpeg, '-y',
        '-f', 'lavfi', '-i', 'color=c=black:s=1280x720:d=70',
        '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=44100:duration=70',
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-shortest',
        str(video_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr)

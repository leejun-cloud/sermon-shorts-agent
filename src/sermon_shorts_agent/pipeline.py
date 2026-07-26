from pathlib import Path
from typing import List

from .models import Candidate
from .transcript import load_transcript, load_highlights
from .scoring import build_candidates
from .utils import ensure_dir, write_json, format_ts


def analyze(transcript_path: Path, highlights_path: Path = None, out_dir: Path = None, top_n: int = 5) -> List[Candidate]:
    segments = load_transcript(transcript_path)
    highlights = load_highlights(highlights_path) if highlights_path else []
    candidates = build_candidates(segments, highlights, top_n=top_n)
    if out_dir:
        ensure_dir(out_dir)
        write_json(out_dir / 'candidates.json', [c.to_dict() for c in candidates])
        (out_dir / 'report.md').write_text(render_report(candidates), encoding='utf-8')
    return candidates


def analyze_workspace(workspace_dir: Path, out_dir: Path = None, top_n: int = 5) -> List[Candidate]:
    transcript = workspace_dir / 'transcript.json'
    if not transcript.exists():
        transcript = workspace_dir / 'transcript.srt'
    if not transcript.exists():
        raise FileNotFoundError(f'transcript not found in workspace: {workspace_dir}')
    highlights = workspace_dir / 'highlights.json'
    return analyze(transcript, highlights if highlights.exists() else None, out_dir, top_n=top_n)


def render_report(candidates: List[Candidate]) -> str:
    lines = ['# sermon-shorts-agent 후보 리포트', '']
    if not candidates:
        lines.append('후보가 없습니다.')
        return '\n'.join(lines) + '\n'
    for c in candidates:
        lines += [
            f"## {c.rank}. {c.title}",
            f"- 구간: `{format_ts(c.start)} ~ {format_ts(c.end)}` ({round(c.end-c.start,1)}초)",
            f"- 카테고리: `{c.category}`",
            f"- 점수: `{c.score}`",
            f"- 훅: {c.hook}",
            f"- 요약: {c.summary}",
            f"- 이유: {', '.join(c.reasons) if c.reasons else '기본 점수 조합'}",
            f"- 해시태그: {' '.join(c.hashtags)}",
            '',
            '> 전사',
            f"> {c.transcript}",
            ''
        ]
    return '\n'.join(lines) + '\n'

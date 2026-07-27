from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Optional

from .pipeline import analyze
from .utils import ensure_dir, read_json, sanitize_slug, write_json
from .youtube import fetch_metadata, fetch_transcript

LEARNING_STOPWORDS = {
    '배우기', '배우고', '배우고싶은', '배우고싶어', '배우고싶다', '유튜브', 'youtube', '공부', '학습',
    '강의', '영상', '방법', '기초', '입문', '심화', '특별한', '프로그램', 'the', 'and', 'for', 'with',
}

ACTION_WORDS = ['해보기', '적용', '실습', '실전', '직접', '예시', '팁', '방법', '단계', 'workflow']
CONCEPT_WORDS = ['정의', '개념', '원리', '핵심', '구조', '이유', '배경', 'overview']


def topic_keywords(topic: str, extra: Optional[List[str]] = None) -> List[str]:
    tokens = re.findall(r'[A-Za-z가-힣0-9]{2,}', str(topic or '').lower())
    cleaned = []
    for token in tokens + [str(x).lower() for x in (extra or []) if str(x).strip()]:
        if token in LEARNING_STOPWORDS:
            continue
        if token not in cleaned:
            cleaned.append(token)
    return cleaned[:10]


def build_learning_preferences(topic: str, base_preferences: Optional[Dict] = None) -> Dict:
    prefs = dict(base_preferences or {})
    must = list(prefs.get('must_include_keywords') or [])
    for kw in topic_keywords(topic):
        if kw not in must:
            must.append(kw)
    prefs['must_include_keywords'] = must[:10]
    prefs.setdefault('preferred_categories', ['message', 'application'])
    prefs.setdefault('target_duration_sec', 50)
    return prefs


def search_youtube_topic(topic: str, limit: int = 5) -> List[Dict]:
    from yt_dlp import YoutubeDL

    query = f'ytsearch{max(1, limit)}:{topic}'
    opts = {'quiet': True, 'no_warnings': True, 'skip_download': True, 'extract_flat': True}
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(query, download=False)
    entries = info.get('entries') or []
    items = []
    for entry in entries:
        video_id = entry.get('id')
        if not video_id:
            continue
        url = entry.get('url') or entry.get('webpage_url') or f'https://www.youtube.com/watch?v={video_id}'
        if not url.startswith('http'):
            url = f'https://www.youtube.com/watch?v={video_id}'
        items.append({
            'id': video_id,
            'title': entry.get('title') or video_id,
            'url': url,
            'uploader': entry.get('uploader') or entry.get('channel'),
            'duration': entry.get('duration'),
            'description': entry.get('description') or '',
        })
    return items


def _merge_sources(topic: str, manual_urls: Optional[List[str]], limit: int, search_related: bool) -> List[Dict]:
    merged: List[Dict] = []
    seen = set()
    if search_related:
        for item in search_youtube_topic(topic, limit=limit):
            url = item.get('url')
            if url and url not in seen:
                merged.append(item)
                seen.add(url)
    for url in manual_urls or []:
        url = str(url or '').strip()
        if not url or url in seen:
            continue
        meta = fetch_metadata(url)
        merged.append({
            'id': meta.get('id'),
            'title': meta.get('title') or url,
            'url': meta.get('webpage_url') or url,
            'uploader': meta.get('uploader'),
            'duration': meta.get('duration'),
            'description': meta.get('description') or '',
        })
        seen.add(url)
    return merged


def _lesson_type(candidate: Dict) -> str:
    category = candidate.get('category')
    transcript = str(candidate.get('transcript') or '')
    lower = transcript.lower()
    if category == 'application' or any(word in lower for word in ACTION_WORDS):
        return 'practice'
    if any(word in lower for word in CONCEPT_WORDS):
        return 'concept'
    if category == 'emotion':
        return 'motivation'
    return 'core'


def _why_recommended(candidate: Dict, topic: str, keywords: List[str]) -> List[str]:
    text = f"{candidate.get('title','')} {candidate.get('summary','')} {candidate.get('transcript','')}".lower()
    notes = []
    matched = [kw for kw in keywords if kw in text]
    if matched:
        notes.append(f"주제 핵심어와 직접 맞닿음: {', '.join(matched[:4])}")
    if candidate.get('match_summary'):
        notes.append(candidate['match_summary'])
    if candidate.get('score_breakdown'):
        notes.append(candidate['score_breakdown'][0])
    notes.append(f"{topic}를 배울 때 바로 써먹기 좋은 { _lesson_type(candidate) } 구간")
    return notes[:4]


def _highlight_from_candidate(video: Dict, candidate: Dict, topic: str, keywords: List[str]) -> Dict:
    transcript = str(candidate.get('transcript') or '').strip()
    excerpt = transcript[:220] + ('…' if len(transcript) > 220 else '')
    return {
        'rank': candidate.get('rank'),
        'start': candidate.get('start'),
        'end': candidate.get('end'),
        'duration': round(float(candidate.get('end', 0)) - float(candidate.get('start', 0)), 2),
        'title': candidate.get('title'),
        'category': candidate.get('category'),
        'lesson_type': _lesson_type(candidate),
        'summary': candidate.get('summary'),
        'excerpt': excerpt,
        'score': candidate.get('score'),
        'reasons': candidate.get('reasons') or [],
        'score_breakdown': candidate.get('score_breakdown') or [],
        'match_summary': candidate.get('match_summary') or '',
        'recommendation_notes': _why_recommended(candidate, topic, keywords),
        'video_url': video.get('url'),
        'video_title': video.get('title'),
    }


def analyze_learning_topic(
    topic: str,
    out_dir: Path,
    *,
    manual_urls: Optional[List[str]] = None,
    search_related: bool = True,
    limit: int = 5,
    per_video_top_n: int = 3,
    preferences: Optional[Dict] = None,
) -> Dict:
    out_dir = ensure_dir(out_dir)
    topic = str(topic or '').strip()
    if not topic:
        raise ValueError('topic is required')
    keywords = topic_keywords(topic)
    learning_prefs = build_learning_preferences(topic, preferences)
    sources = _merge_sources(topic, manual_urls, limit=limit, search_related=search_related)
    videos = []
    all_highlights = []

    for index, source in enumerate(sources, start=1):
        url = source.get('url')
        if not url:
            continue
        safe_name = sanitize_slug(f"{index}-{source.get('id') or source.get('title') or 'video'}")
        video_root = ensure_dir(out_dir / 'videos' / safe_name)
        transcript_path = video_root / 'transcript.json'
        metadata_path = video_root / 'youtube_metadata.json'
        try:
            transcript = fetch_transcript(url, languages=['ko', 'en'])
            write_json(transcript_path, transcript)
            meta = fetch_metadata(url)
            write_json(metadata_path, meta)
            analysis_dir = ensure_dir(video_root / 'analysis')
            candidates = analyze(transcript_path, None, analysis_dir, top_n=per_video_top_n, preferences=learning_prefs)
            highlight_dicts = [_highlight_from_candidate(meta, candidate.to_dict(), topic, keywords) for candidate in candidates]
            if not highlight_dicts and transcript:
                fallback_text = ' '.join(str(item.get('text') or '').strip() for item in transcript[:3]).strip()
                fallback_end = float(transcript[min(len(transcript), 3) - 1].get('end') or transcript[0].get('end') or 0.0)
                highlight_dicts = [{
                    'rank': 1,
                    'start': float(transcript[0].get('start') or 0.0),
                    'end': fallback_end,
                    'duration': round(max(0.0, fallback_end - float(transcript[0].get('start') or 0.0)), 2),
                    'title': f"{topic} 핵심 입문 구간",
                    'category': 'message',
                    'lesson_type': 'concept',
                    'summary': fallback_text[:120] + ('…' if len(fallback_text) > 120 else ''),
                    'excerpt': fallback_text[:220] + ('…' if len(fallback_text) > 220 else ''),
                    'score': 1.0,
                    'reasons': ['후보 엔진 빈 결과 대비 기본 학습 하이라이트'],
                    'score_breakdown': ['+1.00 · 짧은 영상/자막에서도 최소 학습 포인트 보장'],
                    'match_summary': '기본 학습 포인트',
                    'recommendation_notes': [f'{topic} 입문용으로 먼저 보기 좋은 시작 구간'],
                    'video_url': meta.get('webpage_url') or url,
                    'video_title': meta.get('title') or source.get('title') or url,
                }]
            video_score = max((float(item['score']) for item in highlight_dicts), default=0.0)
            video_payload = {
                'rank': 0,
                'title': meta.get('title') or source.get('title') or url,
                'url': meta.get('webpage_url') or url,
                'uploader': meta.get('uploader') or source.get('uploader'),
                'duration': meta.get('duration') or source.get('duration'),
                'description': meta.get('description') or source.get('description') or '',
                'video_id': meta.get('id') or source.get('id'),
                'workspace': str(video_root),
                'highlights': highlight_dicts,
                'top_score': round(video_score, 2),
                'why_video': [
                    f"{topic}와 직접 맞는 하이라이트 {len(highlight_dicts)}개 추출",
                    f"가장 강한 학습 구간 점수 {round(video_score, 2)}",
                ],
            }
            videos.append(video_payload)
            all_highlights.extend(highlight_dicts)
        except Exception as exc:
            videos.append({
                'rank': 0,
                'title': source.get('title') or url,
                'url': url,
                'uploader': source.get('uploader'),
                'duration': source.get('duration'),
                'description': source.get('description') or '',
                'video_id': source.get('id'),
                'workspace': str(video_root),
                'highlights': [],
                'top_score': 0.0,
                'error': str(exc),
                'why_video': [f'분석 실패: {exc}'],
            })

    videos.sort(key=lambda item: (item.get('top_score', 0.0), len(item.get('highlights') or [])), reverse=True)
    for idx, item in enumerate(videos, start=1):
        item['rank'] = idx
    top_highlights = sorted(all_highlights, key=lambda item: float(item.get('score', 0.0)), reverse=True)[:12]

    result = {
        'topic': topic,
        'keywords': keywords,
        'preferences_used': learning_prefs,
        'videos': videos,
        'top_highlights': top_highlights,
        'counts': {
            'videos_considered': len(sources),
            'videos_analyzed': sum(1 for item in videos if not item.get('error')),
            'highlights': len(all_highlights),
        },
    }
    write_json(out_dir / 'learning_results.json', result)
    (out_dir / 'learning_report.md').write_text(render_learning_report(result), encoding='utf-8')
    return result


def render_learning_report(result: Dict) -> str:
    lines = [f"# YouTube 학습 하이라이트 리포트 — {result['topic']}", '']
    lines.append(f"- 핵심어: {', '.join(result.get('keywords') or []) or '-'}")
    counts = result.get('counts') or {}
    lines.append(f"- 분석 영상: {counts.get('videos_analyzed', 0)}/{counts.get('videos_considered', 0)}")
    lines.append(f"- 총 하이라이트: {counts.get('highlights', 0)}")
    lines.append('')
    for video in result.get('videos') or []:
        lines.append(f"## {video.get('rank', '-')}. {video.get('title')}")
        lines.append(f"- 링크: {video.get('url')}")
        if video.get('uploader'):
            lines.append(f"- 채널: {video.get('uploader')}")
        if video.get('error'):
            lines.append(f"- 오류: {video['error']}")
            lines.append('')
            continue
        for item in video.get('highlights') or []:
            lines.append(f"### {item.get('rank')}. {item.get('title')}")
            lines.append(f"- 구간: {item.get('start')}s ~ {item.get('end')}s ({item.get('duration')}초)")
            lines.append(f"- 유형: {item.get('lesson_type')} / score {item.get('score')}")
            lines.append(f"- 요약: {item.get('summary')}")
            lines.append(f"- 추천 이유: {' | '.join(item.get('recommendation_notes') or [])}")
            lines.append('')
    return '\n'.join(lines).strip() + '\n'


def load_learning_results(root: Path) -> Dict:
    return read_json(root / 'learning_results.json')

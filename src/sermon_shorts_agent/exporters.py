from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .learning import load_learning_results
from .utils import ensure_dir, sanitize_slug

NOTION_TOKEN_VARS = ['NOTION_TOKEN', 'NOTION_API_KEY', 'DREAMBRIDGE_TOKEN']


def export_learning_to_obsidian(result_root: Path, vault_path: Path, subdir: str = '03_산출물/강의안/유튜브학습') -> Dict:
    result = load_learning_results(result_root)
    topic = result['topic']
    topic_slug = sanitize_slug(topic)
    base = ensure_dir(Path(vault_path) / subdir / topic_slug)
    hub_path = base / f'{topic_slug}.md'
    lines = [
        f'# {topic} 유튜브 학습 허브',
        '',
        f'- 핵심어: {", ".join(result.get("keywords") or []) or "-"}',
        f'- 분석 영상 수: {result.get("counts", {}).get("videos_analyzed", 0)}',
        f'- 총 하이라이트: {result.get("counts", {}).get("highlights", 0)}',
        '',
        '## 추천 영상',
        '',
    ]
    created_notes = []
    for video in result.get('videos') or []:
        note_name = sanitize_slug(video.get('title') or video.get('video_id') or 'video') + '.md'
        note_path = base / note_name
        created_notes.append(str(note_path))
        hub_link = note_name[:-3]
        lines.append(f"- [[{hub_link}]] — {video.get('url')}")
        note_lines = [
            f"# {video.get('title')}",
            '',
            f"- 주제: {topic}",
            f"- 링크: {video.get('url')}",
            f"- 채널: {video.get('uploader') or '-'}",
            f"- 길이(초): {video.get('duration') or '-'}",
            '',
            '## 추천 이유',
            '',
        ]
        for item in video.get('why_video') or []:
            note_lines.append(f'- {item}')
        note_lines += ['', '## 하이라이트', '']
        for highlight in video.get('highlights') or []:
            note_lines += [
                f"### {highlight.get('rank')}. {highlight.get('title')}",
                f"- 구간: {highlight.get('start')}s ~ {highlight.get('end')}s ({highlight.get('duration')}초)",
                f"- 학습 유형: {highlight.get('lesson_type')}",
                f"- 요약: {highlight.get('summary')}",
                f"- 추천 이유: {' | '.join(highlight.get('recommendation_notes') or [])}",
                f"- 발췌: {highlight.get('excerpt')}",
                '',
            ]
        note_path.write_text('\n'.join(note_lines).strip() + '\n', encoding='utf-8')
    hub_path.write_text('\n'.join(lines).strip() + '\n', encoding='utf-8')
    return {'hub_path': str(hub_path), 'note_count': len(created_notes), 'notes': created_notes}


def _candidate_tokens(explicit_token: Optional[str] = None) -> List[Tuple[str, str]]:
    pairs: List[Tuple[str, str]] = []
    if explicit_token:
        pairs.append(('explicit', explicit_token))
    for name in NOTION_TOKEN_VARS:
        value = os.environ.get(name)
        if value:
            pairs.append((name, value))
    return pairs


def _notion_request(method: str, url: str, token: str, payload: Optional[Dict] = None) -> Dict:
    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header('Authorization', f'Bearer {token}')
    req.add_header('Notion-Version', '2022-06-28')
    req.add_header('Content-Type', 'application/json')
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode('utf-8')
    return json.loads(raw) if raw else {}


def _find_title_property(schema: Dict) -> str:
    for key, value in (schema.get('properties') or {}).items():
        if value.get('type') == 'title':
            return key
    raise RuntimeError('No title property found in Notion database schema')


def _pick_property(schema: Dict, names: List[str], expected_type: Optional[str] = None) -> Optional[str]:
    props = schema.get('properties') or {}
    for name in names:
        if name in props and (expected_type is None or props[name].get('type') == expected_type):
            return name
    return None


def export_learning_to_notion(result_root: Path, database_id: str, token: Optional[str] = None) -> Dict:
    result = load_learning_results(result_root)
    topic = result['topic']
    attempts = []
    errors = []
    schema = None
    used_token_name = None
    used_token = None
    for token_name, candidate in _candidate_tokens(token):
        attempts.append(token_name)
        try:
            schema = _notion_request('GET', f'https://api.notion.com/v1/databases/{database_id}', candidate)
            used_token_name = token_name
            used_token = candidate
            break
        except urllib.error.HTTPError as exc:
            body = exc.read().decode('utf-8', errors='ignore')
            errors.append({'token': token_name, 'status': exc.code, 'body': body})
        except Exception as exc:
            errors.append({'token': token_name, 'status': 'error', 'body': str(exc)})
    if not schema or not used_token:
        raise RuntimeError(f'Notion database access failed: {errors}; attempted tokens={attempts}')

    title_prop = _find_title_property(schema)
    topic_prop = _pick_property(schema, ['주제', 'Topic'], 'rich_text')
    url_prop = _pick_property(schema, ['링크', 'URL', 'Video URL'], 'url')
    channel_prop = _pick_property(schema, ['채널', 'Channel'], 'rich_text')
    status_prop = _pick_property(schema, ['상태', 'Status'], 'select')
    summary_prop = _pick_property(schema, ['요약', 'Summary'], 'rich_text')
    created = []
    for video in result.get('videos') or []:
        properties = {
            title_prop: {'title': [{'text': {'content': f"[{topic}] {video.get('title')}"[:1900]}}]},
        }
        if topic_prop:
            properties[topic_prop] = {'rich_text': [{'text': {'content': topic[:1900]}}]}
        if url_prop:
            properties[url_prop] = {'url': video.get('url')}
        if channel_prop:
            properties[channel_prop] = {'rich_text': [{'text': {'content': str(video.get('uploader') or '-')[:1900]}}]}
        if status_prop:
            properties[status_prop] = {'select': {'name': '정리완료'}}
        if summary_prop:
            summary_text = '; '.join((video.get('why_video') or [])[:2])
            properties[summary_prop] = {'rich_text': [{'text': {'content': summary_text[:1900]}}]}
        children = []
        for highlight in (video.get('highlights') or [])[:5]:
            text = f"[{highlight.get('start')}s~{highlight.get('end')}s] {highlight.get('summary')} / {' | '.join(highlight.get('recommendation_notes') or [])}"
            children.append({
                'object': 'block',
                'type': 'bulleted_list_item',
                'bulleted_list_item': {'rich_text': [{'type': 'text', 'text': {'content': text[:1900]}}]},
            })
        payload = {'parent': {'database_id': database_id}, 'properties': properties, 'children': children}
        page = _notion_request('POST', 'https://api.notion.com/v1/pages', used_token, payload)
        created.append({'id': page.get('id'), 'url': page.get('url'), 'title': video.get('title')})
    return {'database_id': database_id, 'created_count': len(created), 'pages': created, 'token_used': used_token_name}

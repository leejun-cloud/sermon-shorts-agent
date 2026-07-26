from __future__ import annotations

import re
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Dict, List

from .models import Candidate
from .utils import write_json, read_json

DEFAULT_PREFERENCES = {
    'preferred_categories': [],
    'must_include_keywords': [],
    'avoid_keywords': [],
    'target_duration_sec': 45,
    'author_intent': '',
    'hook_tone': '',
    'learning_enabled': True,
    'cookies_from_browser': '',
    'cookies_path': '',
}


def preferences_path(data_root: Path) -> Path:
    return data_root / 'preferences.json'


def feedback_path(data_root: Path) -> Path:
    return data_root / 'feedback_events.json'


def learning_path(data_root: Path) -> Path:
    return data_root / 'learning_summary.json'


def _csv_list(value) -> List[str]:
    if isinstance(value, list):
        items = value
    else:
        items = str(value or '').split(',')
    cleaned = []
    for item in items:
        text = str(item).strip()
        if text:
            cleaned.append(text)
    return cleaned


def normalize_preferences(payload: Dict | None) -> Dict:
    payload = payload or {}
    prefs = deepcopy(DEFAULT_PREFERENCES)
    prefs.update(payload)
    prefs['preferred_categories'] = _csv_list(prefs.get('preferred_categories'))
    prefs['must_include_keywords'] = _csv_list(prefs.get('must_include_keywords'))
    prefs['avoid_keywords'] = _csv_list(prefs.get('avoid_keywords'))
    try:
        prefs['target_duration_sec'] = max(10, min(59, int(float(prefs.get('target_duration_sec') or 45))))
    except Exception:
        prefs['target_duration_sec'] = 45
    prefs['author_intent'] = str(prefs.get('author_intent') or '').strip()
    prefs['hook_tone'] = str(prefs.get('hook_tone') or '').strip()
    prefs['learning_enabled'] = bool(prefs.get('learning_enabled', True))
    prefs['cookies_from_browser'] = str(prefs.get('cookies_from_browser') or '').strip()
    prefs['cookies_path'] = str(prefs.get('cookies_path') or '').strip()
    return prefs


def load_preferences(data_root: Path) -> Dict:
    path = preferences_path(data_root)
    if not path.exists():
        return normalize_preferences({})
    return normalize_preferences(read_json(path))


def save_preferences(data_root: Path, payload: Dict) -> Dict:
    prefs = normalize_preferences(payload)
    write_json(preferences_path(data_root), prefs)
    return prefs


def _tokenize(text: str) -> List[str]:
    return re.findall(r'[A-Za-z가-힣0-9]{2,}', text.lower())


def _intent_keywords(prefs: Dict) -> List[str]:
    raw = prefs.get('author_intent') or ''
    return [token for token in _tokenize(raw) if len(token) >= 2][:12]


def apply_preferences(candidates: List[Candidate], prefs: Dict | None) -> List[Candidate]:
    prefs = normalize_preferences(prefs)
    preferred_categories = set(prefs.get('preferred_categories') or [])
    must_include = [item.lower() for item in prefs.get('must_include_keywords') or []]
    avoid_keywords = [item.lower() for item in prefs.get('avoid_keywords') or []]
    target_duration = int(prefs.get('target_duration_sec') or 45)
    learned = prefs.get('learned', {}) if isinstance(prefs.get('learned'), dict) else {}
    learned_categories = set(learned.get('preferred_categories') or [])
    intent_keywords = [kw.lower() for kw in _intent_keywords(prefs)]

    for candidate in candidates:
        text = f"{candidate.title} {candidate.summary} {candidate.transcript}".lower()
        duration = max(1.0, candidate.end - candidate.start)
        bonus = 0.0
        reasons = list(candidate.reasons)

        if candidate.category in preferred_categories:
            bonus += 2.4
            reasons.append('저자 선호 카테고리와 일치')
        if candidate.category in learned_categories:
            bonus += 1.6
            reasons.append('이전 선택 패턴과 유사')
        for kw in must_include:
            if kw and kw in text:
                bonus += 0.9
                reasons.append(f'필수 키워드 포함: {kw}')
        for kw in intent_keywords:
            if kw and kw in text:
                bonus += 0.45
                reasons.append(f'저자 의도와 맞는 표현: {kw}')
        for kw in avoid_keywords:
            if kw and kw in text:
                bonus -= 1.2
                reasons.append(f'피하고 싶은 표현 포함: {kw}')
        closeness = max(0.0, 1.0 - abs(duration - target_duration) / max(10.0, target_duration))
        if closeness > 0.15:
            bonus += round(closeness * 1.2, 2)
            reasons.append('선호 길이에 근접')

        candidate.score = round(candidate.score + bonus, 2)
        candidate.reasons = sorted(dict.fromkeys(reasons))

    reranked = sorted(candidates, key=lambda c: c.score, reverse=True)
    for idx, candidate in enumerate(reranked, start=1):
        candidate.rank = idx
    return reranked


def load_feedback_events(data_root: Path) -> List[Dict]:
    path = feedback_path(data_root)
    if not path.exists():
        return []
    data = read_json(path)
    return data if isinstance(data, list) else []


def save_feedback_event(data_root: Path, event: Dict) -> Dict:
    events = load_feedback_events(data_root)
    events.append(event)
    write_json(feedback_path(data_root), events)
    summary = summarize_feedback(events)
    write_json(learning_path(data_root), summary)
    return summary


def summarize_feedback(events: List[Dict]) -> Dict:
    selected = [e for e in events if e.get('selected')]
    category_counter = Counter(e.get('category') for e in selected if e.get('category'))
    note_counter = Counter()
    start_deltas = []
    end_deltas = []
    durations = []
    for event in selected:
        start_delta = event.get('start_delta')
        end_delta = event.get('end_delta')
        if isinstance(start_delta, (int, float)):
            start_deltas.append(float(start_delta))
        if isinstance(end_delta, (int, float)):
            end_deltas.append(float(end_delta))
        duration = event.get('selected_duration')
        if isinstance(duration, (int, float)):
            durations.append(float(duration))
        note_counter.update(_tokenize(str(event.get('note') or '')))
        note_counter.update(_tokenize(str(event.get('author_intent') or '')))
    preferred_categories = [name for name, _ in category_counter.most_common(2)]
    return {
        'total_events': len(events),
        'selected_events': len(selected),
        'preferred_categories': preferred_categories,
        'category_counts': dict(category_counter),
        'avg_start_delta': round(sum(start_deltas) / len(start_deltas), 2) if start_deltas else 0.0,
        'avg_end_delta': round(sum(end_deltas) / len(end_deltas), 2) if end_deltas else 0.0,
        'avg_selected_duration': round(sum(durations) / len(durations), 2) if durations else 0.0,
        'common_note_keywords': [word for word, _ in note_counter.most_common(8)],
    }


def load_learning_summary(data_root: Path) -> Dict:
    path = learning_path(data_root)
    if not path.exists():
        return summarize_feedback([])
    data = read_json(path)
    return data if isinstance(data, dict) else summarize_feedback([])

from __future__ import annotations

import re
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Dict, List

from .models import Candidate
from .utils import read_json, write_json

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

CATEGORY_LABELS = {
    'message': '핵심 메시지형',
    'emotion': '감정 피크형',
    'application': '적용 포인트형',
    'scripture': '본문 선포형',
    'manual': '수동 선택형',
}


def preferences_path(data_root: Path) -> Path:
    return data_root / 'preferences.json'


def feedback_path(data_root: Path) -> Path:
    return data_root / 'feedback_events.json'


def learning_path(data_root: Path) -> Path:
    return data_root / 'learning_summary.json'


def author_profile_path(data_root: Path) -> Path:
    return data_root / 'author_profile.json'


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
    refresh_author_profile(data_root)
    return prefs


def _tokenize(text: str) -> List[str]:
    return re.findall(r'[A-Za-z가-힣0-9]{2,}', text.lower())


def _intent_keywords(prefs: Dict) -> List[str]:
    raw = prefs.get('author_intent') or ''
    return [token for token in _tokenize(raw) if len(token) >= 2][:12]


def _format_bonus(amount: float, message: str) -> str:
    sign = '+' if amount >= 0 else ''
    return f'{sign}{amount:.2f} · {message}'


def _hook_note(hook_tone: str, text: str) -> str | None:
    if not hook_tone:
        return None
    mapping = {
        'declarative': '선언형 훅을 선호하는 설정과 맞는지 확인됨',
        'warm': '부드러운 권면형 훅 선호와 맞는 표현이 포함됨',
        'urgent': '강한 촉구형 훅 선호와 맞는 어조가 살아 있음',
    }
    note = mapping.get(hook_tone)
    if not note:
        return None
    lower = text.lower()
    if hook_tone == 'urgent' and any(word in lower for word in ['반드시', '지금', 'must', 'now']):
        return note
    if hook_tone == 'warm' and any(word in lower for word in ['위로', '사랑', '은혜', 'grace', 'love']):
        return note
    if hook_tone == 'declarative' and any(word in lower for word in ['입니다', '이다', 'this is', 'it is']):
        return note
    return None


def apply_preferences(candidates: List[Candidate], prefs: Dict | None) -> List[Candidate]:
    prefs = normalize_preferences(prefs)
    preferred_categories = set(prefs.get('preferred_categories') or [])
    must_include = [item.lower() for item in prefs.get('must_include_keywords') or []]
    avoid_keywords = [item.lower() for item in prefs.get('avoid_keywords') or []]
    target_duration = int(prefs.get('target_duration_sec') or 45)
    learned = prefs.get('learned', {}) if isinstance(prefs.get('learned'), dict) else {}
    author_profile = prefs.get('author_profile', {}) if isinstance(prefs.get('author_profile'), dict) else {}
    learned_categories = set(learned.get('preferred_categories') or [])
    intent_keywords = [kw.lower() for kw in _intent_keywords(prefs)]
    avg_start_delta = float(learned.get('avg_start_delta') or 0.0)
    avg_end_delta = float(learned.get('avg_end_delta') or 0.0)

    for candidate in candidates:
        text = f"{candidate.title} {candidate.summary} {candidate.transcript}".lower()
        duration = max(1.0, candidate.end - candidate.start)
        bonus = 0.0
        reasons = list(candidate.reasons)
        breakdown: List[str] = []
        notes: List[str] = []

        if candidate.category in preferred_categories:
            bonus += 2.4
            reasons.append('저자 선호 카테고리와 일치')
            breakdown.append(_format_bonus(2.4, f'선호 카테고리 {CATEGORY_LABELS.get(candidate.category, candidate.category)}'))
        if candidate.category in learned_categories:
            bonus += 1.6
            reasons.append('이전 선택 패턴과 유사')
            breakdown.append(_format_bonus(1.6, '이전 선택 로그에서 자주 고른 유형'))
        for kw in must_include:
            if kw and kw in text:
                bonus += 0.9
                reasons.append(f'필수 키워드 포함: {kw}')
                breakdown.append(_format_bonus(0.9, f'필수 키워드 `{kw}` 포함'))
        for kw in intent_keywords:
            if kw and kw in text:
                bonus += 0.45
                reasons.append(f'저자 의도와 맞는 표현: {kw}')
                breakdown.append(_format_bonus(0.45, f'저자 의도 키워드 `{kw}` 반영'))
        for kw in avoid_keywords:
            if kw and kw in text:
                bonus -= 1.2
                reasons.append(f'피하고 싶은 표현 포함: {kw}')
                breakdown.append(_format_bonus(-1.2, f'회피 키워드 `{kw}` 포함'))
        closeness = max(0.0, 1.0 - abs(duration - target_duration) / max(10.0, target_duration))
        if closeness > 0.15:
            closeness_bonus = round(closeness * 1.2, 2)
            bonus += closeness_bonus
            reasons.append('선호 길이에 근접')
            breakdown.append(_format_bonus(closeness_bonus, f'선호 길이 {target_duration}초에 근접'))

        hook_note = _hook_note(prefs.get('hook_tone') or '', text)
        if hook_note:
            bonus += 0.5
            breakdown.append(_format_bonus(0.5, hook_note))
            notes.append(hook_note)

        if abs(avg_start_delta) >= 0.7:
            direction = '앞을 더 당기는' if avg_start_delta > 0 else '앞 여백을 조금 남기는'
            notes.append(f'이전 편집 패턴상 {abs(avg_start_delta):.1f}초 정도 {direction} 경향이 있습니다.')
        if abs(avg_end_delta) >= 0.7:
            direction = '뒤를 더 늘리는' if avg_end_delta > 0 else '뒤를 더 타이트하게 자르는'
            notes.append(f'이전 편집 패턴상 {abs(avg_end_delta):.1f}초 정도 {direction} 경향이 있습니다.')

        profile_keywords = author_profile.get('signature_keywords') or []
        matched_profile_keywords = [kw for kw in profile_keywords if kw.lower() in text]
        if matched_profile_keywords:
            notes.append(f"저자 프로필 핵심어와 겹침: {', '.join(matched_profile_keywords[:3])}")

        candidate.score = round(candidate.score + bonus, 2)
        candidate.reasons = sorted(dict.fromkeys(reasons))
        candidate.score_breakdown = breakdown or ['+0.00 · 추가 선호 보정 없음']
        headline_bits = []
        if candidate.category in preferred_categories:
            headline_bits.append('선호 카테고리 일치')
        if matched_profile_keywords:
            headline_bits.append('저자 프로필 키워드 일치')
        if any(kw in text for kw in must_include):
            headline_bits.append('필수 키워드 반영')
        if closeness > 0.6:
            headline_bits.append('길이 적합')
        candidate.match_summary = ' · '.join(headline_bits[:3]) or '기본 점수 기준으로 추천된 후보'
        candidate.recommendation_notes = sorted(dict.fromkeys(notes))[:4]

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
    refresh_author_profile(data_root, events=events, summary=summary)
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


def build_author_profile(prefs: Dict, summary: Dict, events: List[Dict]) -> Dict:
    prefs = normalize_preferences(prefs)
    summary = summary if isinstance(summary, dict) else summarize_feedback(events)
    signature_keywords = []
    for word in (prefs.get('must_include_keywords') or []) + (summary.get('common_note_keywords') or []):
        if word and word not in signature_keywords:
            signature_keywords.append(word)
    top_category = (summary.get('preferred_categories') or prefs.get('preferred_categories') or ['message'])[0]
    avg_duration = summary.get('avg_selected_duration') or prefs.get('target_duration_sec') or 45
    editing_tendencies = []
    start_delta = float(summary.get('avg_start_delta') or 0.0)
    end_delta = float(summary.get('avg_end_delta') or 0.0)
    if abs(start_delta) < 0.7:
        editing_tendencies.append('후보 시작점은 크게 바꾸지 않는 편')
    elif start_delta > 0:
        editing_tendencies.append(f'도입부를 평균 {abs(start_delta):.1f}초 더 뒤에서 시작하는 편')
    else:
        editing_tendencies.append(f'도입부를 평균 {abs(start_delta):.1f}초 더 앞당기는 편')
    if abs(end_delta) < 0.7:
        editing_tendencies.append('후보 끝점도 원안과 크게 다르지 않음')
    elif end_delta > 0:
        editing_tendencies.append(f'마무리를 평균 {abs(end_delta):.1f}초 더 길게 가져가는 편')
    else:
        editing_tendencies.append(f'마무리를 평균 {abs(end_delta):.1f}초 더 타이트하게 자르는 편')

    style_rules = []
    if prefs.get('author_intent'):
        style_rules.append(f"저자 의도: {prefs['author_intent']}")
    if prefs.get('preferred_categories'):
        style_rules.append('선호 구간: ' + ', '.join(CATEGORY_LABELS.get(c, c) for c in prefs['preferred_categories']))
    if prefs.get('must_include_keywords'):
        style_rules.append('반드시 살릴 키워드: ' + ', '.join(prefs['must_include_keywords'][:5]))
    if prefs.get('avoid_keywords'):
        style_rules.append('가급적 뺄 키워드: ' + ', '.join(prefs['avoid_keywords'][:5]))
    if prefs.get('hook_tone'):
        style_rules.append(f"훅 톤 선호: {prefs['hook_tone']}")

    if top_category == 'application':
        headline = f'적용 중심형 저자 — {avg_duration:.0f}초 안팎에서 실천 문장이 살아나는 구간을 선호'
    elif top_category == 'emotion':
        headline = f'감정 피크형 저자 — {avg_duration:.0f}초 안팎에서 고조되는 호소를 선호'
    elif top_category == 'scripture':
        headline = f'본문 선포형 저자 — {avg_duration:.0f}초 안팎에서 성경 본문 울림을 살리는 편'
    else:
        headline = f'핵심 메시지형 저자 — {avg_duration:.0f}초 안팎에서 메시지가 또렷한 구간을 선호'

    profile = {
        'headline': headline,
        'top_category': top_category,
        'top_category_label': CATEGORY_LABELS.get(top_category, top_category),
        'signature_keywords': signature_keywords[:8],
        'style_rules': style_rules[:6],
        'editing_tendencies': editing_tendencies[:4],
        'recommended_duration_sec': avg_duration,
        'explanation_template': f"{CATEGORY_LABELS.get(top_category, top_category)} 위주로 보되, {avg_duration:.0f}초 안팎과 핵심 키워드 일치를 우선 확인",
        'source_event_count': len(events),
    }
    return profile


def refresh_author_profile(data_root: Path, *, events: List[Dict] | None = None, summary: Dict | None = None, prefs: Dict | None = None) -> Dict:
    prefs = normalize_preferences(prefs or load_preferences(data_root))
    events = events if events is not None else load_feedback_events(data_root)
    summary = summary if summary is not None else load_learning_summary(data_root)
    profile = build_author_profile(prefs, summary, events)
    write_json(author_profile_path(data_root), profile)
    return profile


def load_author_profile(data_root: Path) -> Dict:
    path = author_profile_path(data_root)
    if not path.exists():
        return refresh_author_profile(data_root)
    data = read_json(path)
    return data if isinstance(data, dict) else refresh_author_profile(data_root)

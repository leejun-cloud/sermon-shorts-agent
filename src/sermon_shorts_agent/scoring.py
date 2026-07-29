import math
import re
from typing import Dict, List, Tuple

from .models import Segment, Highlight, Candidate
from .utils import sentence_chunks

MESSAGE_KEYWORDS = [
    '하나님', '예수', '복음', '은혜', '말씀', '믿음', '소망', '사랑', '순종',
    '회복', '결단', '기도', '부르심', '십자가', '성령',
    'god', 'jesus', 'gospel', 'grace', 'word', 'faith', 'hope', 'love', 'obedience',
    'restore', 'calling', 'prayer', 'truth', 'message'
]
EMOTION_KEYWORDS = [
    '지금', '반드시', '결코', '돌아오', '울', '회개', '두려워', '살리', '일어나',
    '회복', '강하게', '절대로', '믿으', '붙잡',
    'now', 'must', 'never', 'return', 'fear', 'rise', 'hold on', 'courage', 'again'
]
APPLICATION_KEYWORDS = [
    '오늘', '이번 주', '실천', '적용', '살아내', '행동', '결단', '순종', '시작', '멈추',
    'today', 'this week', 'practice', 'apply', 'action', 'decision', 'start', 'stop', 'step'
]
SCRIPTURE_BOOKS = [
    '창세기', '출애굽기', '레위기', '민수기', '신명기', '여호수아', '사사기', '룻기',
    '사무엘상', '사무엘하', '열왕기상', '열왕기하', '역대상', '역대하', '에스라', '느헤미야',
    '에스더', '욥기', '시편', '잠언', '전도서', '아가', '이사야', '예레미야', '에스겔',
    '다니엘', '호세아', '요엘', '아모스', '오바댜', '요나', '미가', '나훔', '하박국',
    '스바냐', '학개', '스가랴', '말라기', '마태복음', '마가복음', '누가복음', '요한복음',
    '사도행전', '로마서', '고린도전서', '고린도후서', '갈라디아서', '에베소서', '빌립보서',
    '골로새서', '데살로니가전서', '데살로니가후서', '디모데전서', '디모데후서', '디도서',
    '빌레몬서', '히브리서', '야고보서', '베드로전서', '베드로후서', '요한일서', '요한이서',
    '요한삼서', '유다서', '요한계시록',
    'genesis', 'exodus', 'psalm', 'psalms', 'proverbs', 'isaiah', 'matthew', 'mark', 'luke', 'john',
    'romans', 'corinthians', 'ephesians', 'philippians', 'hebrews', 'james', 'revelation'
]


def keyword_hits(text: str, keywords: List[str]) -> int:
    lower = text.lower()
    return sum(1 for kw in keywords if kw.lower() in lower)


def overlaps(a_start: float, a_end: float, b_start: float, b_end: float) -> bool:
    return max(a_start, b_start) < min(a_end, b_end)


def segment_features(segment: Segment, highlights: List[Highlight]) -> Dict[str, float]:
    text = segment.text.strip()
    message = keyword_hits(text, MESSAGE_KEYWORDS)
    emotion = keyword_hits(text, EMOTION_KEYWORDS)
    application = keyword_hits(text, APPLICATION_KEYWORDS)
    scripture = 1 if any(book in text for book in SCRIPTURE_BOOKS) else 0
    exclaim = text.count('!') + text.count('?') * 0.5
    quoteable = 1 if 10 <= len(text) <= 90 else 0
    highlight_bonus = 0.0
    for hl in highlights:
        if overlaps(segment.start, segment.end, hl.start, hl.end):
            highlight_bonus = max(highlight_bonus, 2.5 + hl.score / 4.0)
    score = (
        message * 1.8 + emotion * 1.6 + application * 1.4 + scripture * 2.0 +
        exclaim * 0.5 + quoteable * 1.0 + highlight_bonus
    )
    return {
        'message': float(message),
        'emotion': float(emotion),
        'application': float(application),
        'scripture': float(scripture),
        'exclaim': float(exclaim),
        'highlight_bonus': float(highlight_bonus),
        'score': float(score),
    }


MIN_MEANINGFUL_SENTENCE_LEN = 8


def _first_meaningful_sentence(sentences: List[str]) -> str:
    """후보 구간이 문장 중간(이전 문장의 꼬리)에서 시작할 때, 그 잘린 조각
    ("합니다.", ">> 아멘.") 대신 뒤따르는 온전한 문장을 제목/훅으로 쓴다."""
    for sentence in sentences:
        cleaned = re.sub(r'^>>\s*', '', sentence).strip(' .!?')
        if len(cleaned) >= MIN_MEANINGFUL_SENTENCE_LEN:
            return sentence
    return sentences[0] if sentences else ''


def choose_title(text: str, category: str) -> str:
    sentences = sentence_chunks(text)
    base = _first_meaningful_sentence(sentences) if sentences else text.strip()
    base = re.sub(r'\s+', ' ', base).strip(' .!')
    if len(base) > 42:
        base = base[:39].rstrip() + '...'
    prefixes = {
        'message': '핵심메시지',
        'emotion': '감정피크',
        'application': '적용포인트',
        'scripture': '말씀선포',
    }
    return f"{prefixes.get(category, '쇼츠')} | {base}"


def classify(feature_totals: Dict[str, float]) -> str:
    keys = ['message', 'emotion', 'application', 'scripture']
    return max(keys, key=lambda key: feature_totals.get(key, 0.0))


def generate_hook(text: str, category: str) -> str:
    sentences = sentence_chunks(text)
    first = _first_meaningful_sentence(sentences) if sentences else text.strip()
    if len(first) > 55:
        first = first[:52].rstrip() + '...'
    if category == 'emotion' and not first.endswith('!'):
        return first + '!'
    return first


def summarize(text: str) -> str:
    sentences = sentence_chunks(text)
    if not sentences:
        return text.strip()
    joined = ' '.join(sentences[:2])
    return joined[:160].strip()


def candidate_hashtags(category: str) -> List[str]:
    base = ['#설교쇼츠', '#목회자AI', '#교회콘텐츠']
    extra = {
        'message': ['#핵심메시지', '#말씀요약'],
        'emotion': ['#은혜로운말씀', '#감동클립'],
        'application': ['#말씀적용', '#이번주실천'],
        'scripture': ['#성경말씀', '#본문묵상'],
    }
    return base + extra.get(category, [])


def _ends_sentence(text: str) -> bool:
    """세그먼트가 문장을 끝내는지 판단. 이 트랜스크립트(faster-whisper)는 문장 끝에
    마침표/물음표/느낌표를 붙여주므로 그것을 1차 신호로 쓴다."""
    t = text.rstrip().rstrip('"”\'')
    return t.endswith(('.', '!', '?', '…'))


# 의미 단락 컷 파라미터: 문장 중간에서 끊지 않고, 필요하면 1분을 넘겨도 문장 끝에서 마무리한다.
_CHAR_MAX = 1500


def build_candidates(segments: List[Segment], highlights: List[Highlight], max_duration: float = 90.0, min_duration: float = 18.0, top_n: int = 5) -> List[Candidate]:
    if not segments:
        return []
    total_duration = max((seg.end for seg in segments), default=0.0) - min((seg.start for seg in segments), default=0.0)
    if total_duration and total_duration < min_duration:
        min_duration = max(4.0, min(total_duration, 10.0))
        max_duration = max(min_duration + 4.0, min(30.0, total_duration + 4.0))
    features = [segment_features(seg, highlights) for seg in segments]
    seeds = sorted(range(len(segments)), key=lambda idx: features[idx]['score'], reverse=True)
    used: List[Tuple[float, float]] = []
    candidates: List[Candidate] = []
    for idx in seeds:
        if len(candidates) >= top_n:
            break
        if features[idx]['score'] < 2.4:
            continue
        left = idx
        right = idx
        start = segments[idx].start
        end = segments[idx].end
        # LEFT: 문장 시작 지점으로 정렬 — 앞 세그먼트가 문장을 끝냈으면 현재가 깔끔한 시작점이다.
        # (이전에 "합니다. 우리가..." 처럼 앞 문장 꼬리에서 시작하던 문제를 방지)
        while left > 0:
            if (end - segments[left - 1].start) > max_duration:
                break
            if len(' '.join(seg.text for seg in segments[left - 1:right + 1])) > _CHAR_MAX:
                break
            if _ends_sentence(segments[left - 1].text):
                break
            left -= 1
            start = segments[left].start
        # RIGHT: 최소 길이를 채운 뒤 '문장 끝'에서 마무리한다. 문장이 안 끝났으면 계속 확장.
        last_sentence_end = right if _ends_sentence(segments[right].text) else None
        while right + 1 < len(segments):
            if (segments[right + 1].end - start) > max_duration:
                break
            if len(' '.join(seg.text for seg in segments[left:right + 2])) > _CHAR_MAX:
                break
            right += 1
            end = segments[right].end
            if _ends_sentence(segments[right].text):
                last_sentence_end = right
                if (end - start) >= min_duration:
                    break
        # 문장 중간에서 끊긴 경우, 범위 내 마지막 문장 끝으로 되돌려 의미가 완결되게 한다.
        if (last_sentence_end is not None and last_sentence_end < right
                and (segments[last_sentence_end].end - start) >= min_duration):
            right = last_sentence_end
            end = segments[right].end
        if end - start < min_duration:
            continue
        if any(max(start, s) < min(end, e) for s, e in used):
            continue
        selected = segments[left:right + 1]
        text = ' '.join(seg.text for seg in selected)
        totals = {'message': 0.0, 'emotion': 0.0, 'application': 0.0, 'scripture': 0.0}
        total_score = 0.0
        reasons = []
        for j in range(left, right + 1):
            total_score += features[j]['score']
            for key in totals:
                totals[key] += features[j][key]
            if features[j]['highlight_bonus'] > 0:
                reasons.append('오디오 피크와 겹침')
            if features[j]['scripture'] > 0:
                reasons.append('성경구절/성경책 언급')
            if features[j]['application'] > 0:
                reasons.append('적용형 표현 포함')
        category = classify(totals)
        if totals['message'] > 0:
            reasons.append('핵심 메시지 키워드 포함')
        if totals['emotion'] > 0:
            reasons.append('감정 강조 어휘 포함')
        reasons = sorted(dict.fromkeys(reasons))
        title = choose_title(text, category)
        hook = generate_hook(text, category)
        candidate = Candidate(
            rank=len(candidates) + 1,
            start=round(start, 3),
            end=round(end, 3),
            score=round(total_score, 2),
            category=category,
            title=title,
            summary=summarize(text),
            hook=hook,
            transcript=text,
            reasons=reasons,
            hashtags=candidate_hashtags(category),
            segments=selected,
        )
        used.append((candidate.start, candidate.end))
        candidates.append(candidate)
    return candidates

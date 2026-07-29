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


# 선언·명령형 한국어 종결(제목감이 좋은 문장의 끝). 완결·단정적인 어미를 선호한다.
_TITLE_ENDINGS = ('니다', '습니다', '입니다', '세요', '십시오', '십시다', '합시다',
                  '겠죠', '군요', '나요', '까요', '을까', '읍시다', '어야', '야죠')
_TITLE_STOPWORD_STARTS = ('그러므로', '그런데', '그래서', '그리고', '그래도',
                          '그러니까', '왜냐하면', '그러면', '그러나', '그때', '그러자')
_TITLE_IDEAL_MIN, _TITLE_IDEAL_MAX, _TITLE_HARD_MAX = 12, 34, 42


def _clean_sentence(sentence: str) -> str:
    """ASR 화자표시(>>)·중복 공백을 정리한 한 줄 문장."""
    return re.sub(r'\s+', ' ', sentence.replace('>>', ' ')).strip()


def _title_score(sentence: str) -> float:
    """한 문장이 '제목'으로 얼마나 좋은지 점수. 짧고 완결적이며 핵심 키워드가
    있는 선언형 문장을 선호한다. 외부 API 없이 결정론적으로 뽑는다."""
    core = _clean_sentence(sentence).strip(' .!?"\'”’')
    n = len(core)
    if n < 6:
        return -1.0
    score = 0.0
    if _TITLE_IDEAL_MIN <= n <= _TITLE_IDEAL_MAX:
        score += 3.0
    elif 8 <= n <= _TITLE_HARD_MAX:
        score += 1.5
    else:
        score -= 1.0  # 너무 짧거나 길다
    msg_hits = keyword_hits(core, MESSAGE_KEYWORDS)
    emo_hits = keyword_hits(core, EMOTION_KEYWORDS)
    score += min(msg_hits, 3) * 1.0
    score += min(emo_hits, 2) * 0.7
    if msg_hits + emo_hits == 0:
        score -= 1.0  # 핵심 어휘가 전혀 없으면 제목감이 약하다("그렇지 않습니다" 류)
    if _clean_sentence(sentence).rstrip('"\'”’').endswith(('.', '!', '?')):
        score += 1.2  # 완결된 문장
    if core.endswith(_TITLE_ENDINGS):
        score += 0.9  # 선언·명령형 종결
    if core.startswith(_TITLE_STOPWORD_STARTS):
        score -= 1.2  # 접속사/군말로 시작
    return score


# 제목 맨 앞의 군더더기 부사/디스코스 마커 — 있으면 떼어 제목을 간결하게.
_TITLE_LEAD_FILLERS = ('근본적으로는', '근본적으로', '사실은', '사실', '결국은', '결국',
                       '이제는', '이제', '정말로', '진짜로', '한마디로', '어떻게 보면')


def _strip_lead_filler(base: str) -> str:
    for filler in _TITLE_LEAD_FILLERS:
        if base.startswith(filler + ' '):
            return base[len(filler):].strip()
    return base


def _shorten_title(base: str, limit: int = _TITLE_HARD_MAX) -> str:
    """한도를 넘으면 단어 경계에서 잘라 말줄임(…). 단어 중간을 자르지 않는다."""
    if len(base) <= limit:
        return base
    cut = base[:limit]
    if ' ' in cut[limit // 2:]:  # 뒤쪽에 공백이 있으면 거기서 자른다
        cut = cut[:cut.rfind(' ')]
    return cut.rstrip(' ,·') + '…'


def choose_title(text: str, category: str) -> str:
    sentences = sentence_chunks(text)
    if not sentences:
        base = text.strip()
    else:
        best = max(sentences, key=_title_score)
        if _title_score(best) <= 0:  # 쓸 만한 문장이 없으면 첫 의미 문장으로 폴백
            best = _first_meaningful_sentence(sentences)
        base = _clean_sentence(best).strip(' .!?"\'”’')
    base = _shorten_title(_strip_lead_filler(base))
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

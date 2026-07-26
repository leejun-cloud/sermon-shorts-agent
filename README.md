# sermon-shorts-agent

설교/강의 영상에서 **핵심 메시지형 쇼츠 후보**와 **감정 피크형 쇼츠 후보**를 자동으로 골라내고, 1분 이하 세로형 MP4로 잘라내는 로컬 우선 Python CLI입니다.

이 프로젝트는 `timecode-agent`와 잘 맞습니다.

- `timecode-agent`가 잘하는 것: 전사, 하이라이트, OCR, 장면 신호 생성
- `sermon-shorts-agent`가 하는 것: 설교용 쇼츠 후보 점수화, 60초 이내 후보 선택, 자막 SRT 생성, 세로형 MP4 렌더링

## 핵심 기능

- `timecode-agent` 워크스페이스(`transcript.json`, `highlights.json`) 직접 읽기
- 핵심 메시지 / 적용 / 감정 피크 / 성경구절 언급을 기준으로 후보 점수화
- 15~60초 길이의 쇼츠 후보 자동 생성
- 후보별 제목/설명/해시태그 초안 생성
- 세로형(9:16) MP4 + 클립별 SRT 렌더링
- 데모 영상/데모 전사 자동 생성으로 바로 테스트 가능

## 설치

```bash
cd sermon-shorts-agent
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

## 가장 빠른 데모

```bash
sermon-shorts demo ./demo-output
```

생성물:
- `demo-output/demo-video.mp4`
- `demo-output/candidates.json`
- `demo-output/shorts/*.mp4`
- `demo-output/shorts/*.srt`
- `demo-output/report.md`

## 실제 설교 영상에서 쓰는 순서

### 1) timecode-agent로 전사/신호 생성

```bash
va ingest /path/to/sermon.mp4 --out ./workspace --signals
va highlights ./workspace
```

### 2) 쇼츠 후보 분석

```bash
sermon-shorts analyze-workspace ./workspace --out ./shorts-analysis
```

### 3) 쇼츠 렌더링

```bash
sermon-shorts render \
  --video /path/to/sermon.mp4 \
  --candidates ./shorts-analysis/candidates.json \
  --out ./shorts-analysis/rendered \
  --top 3
```

## 입력 형식

### transcript.json
`timecode-agent`와 호환되는 가장 단순한 배열 형식:

```json
[
  {"start": 0.0, "end": 4.2, "text": "오늘 우리는 두려움보다 말씀을 붙잡아야 합니다."}
]
```

### highlights.json
선택 입력. `timecode-agent` 기본 출력과 동일한 형태:

```json
[
  {"start": 12.0, "end": 18.0, "score": 7.1, "peak_db": -4.2}
]
```

## 점수 로직

후보 점수는 대략 아래 신호를 합산합니다.

- 핵심 메시지 문장(선언형, 강조형)
- 감정 강조 어휘 / 느낌표 / 피크 구간 중첩
- 적용 어휘(오늘, 이번 주, 실천, 결단, 순종…)
- 성경구절 / 성경책 이름 언급
- 60초 이하로 자연스럽게 잘리는가

## 현재 구현 범위

구현됨:
- 쇼츠 후보 자동 선별
- 세로형 클립 렌더링
- 후보별 자막 SRT 생성
- 업로드용 제목/설명/해시태그 초안 생성

아직 미구현:
- YouTube OAuth 업로드
- fancy 자막 디자인(색 강조, 애니메이션)
- 다중 얼굴 추적 기반 스마트 크롭

## 테스트

```bash
python -m unittest discover -s tests -v
```

# sermon-shorts-agent

설교/강의 영상에서 **핵심 메시지형 쇼츠 후보**와 **감정 피크형 쇼츠 후보**를 자동으로 골라내고, 1분 이하 세로형 MP4로 잘라내는 로컬 우선 Python CLI입니다.

이 프로젝트는 `timecode-agent`와 잘 맞습니다.

- `timecode-agent`가 잘하는 것: 전사, 하이라이트, OCR, 장면 신호 생성
- `sermon-shorts-agent`가 하는 것: 설교용 쇼츠 후보 점수화, 60초 이내 후보 선택, 자막 SRT/VTT 생성, 세로형 MP4 렌더링
- 새 기능: **타임라인+자막 웹 스튜디오**, **YouTube 링크/실제 MP4 공통 입력**, **후보 구간 수동 지정 후 바로 추출**, **저자 의도/선택 패턴 학습**

## 핵심 기능

- `timecode-agent` 워크스페이스(`transcript.json`, `highlights.json`) 직접 읽기
- **YouTube URL에서 transcript/metadata/video 직접 가져오기**
- **실제 MP4 업로드 시 faster-whisper로 자동 전사**
- 핵심 메시지 / 적용 / 감정 피크 / 성경구절 언급을 기준으로 후보 점수화
- 15~60초 길이의 쇼츠 후보 자동 생성
- 후보별 제목/설명/해시태그 초안 생성
- **후보 구간 MP3 preview 생성**
- **타임라인 + 전체 자막 + 후보 구간 클릭 이동 + 수동 start/end 지정 UI**
- **저자 의도 / 필수·회피 키워드 / 선호 길이 / 선호 카테고리 저장**
- **선택 후 start/end 수정 패턴을 기록해서 다음 추천에 반영**
- **author_profile.json 자동 생성 + 후보별 추천 이유/점수 보정 내역 표시**
- 세로형(9:16) MP4 + 클립별 SRT/VTT 렌더링
- 데모 영상/데모 전사 자동 생성으로 바로 테스트 가능

## 설치

```bash
cd sermon-shorts-agent
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

## 맥북 로컬 실행 (A안 추천)

가장 쉬운 방법은 아래 파일을 더블클릭하는 것입니다.

```bash
scripts/macos/run-local.command
```

또는 터미널에서:

```bash
bash scripts/macos/run-local.sh
```

이 스크립트는:
1. `.venv` 생성
2. 의존성 설치
3. `sermon-shorts-web` 실행
4. 브라우저를 자동으로 `http://127.0.0.1:8787` 로 엽니다.

## 웹 스튜디오 실행 (추천)

```bash
sermon-shorts-web --host 127.0.0.1 --port 8787
```

브라우저에서 `http://127.0.0.1:8787` 로 열면 다음 흐름을 한 화면에서 처리합니다.

1. YouTube 링크 입력 또는 MP4 업로드
2. 브라우저 쿠키(Chrome/Safari 등) 선택
3. 저자 의도 / 선호 카테고리 / 필수·회피 키워드 입력
4. 자동 전사/분석
5. 추천 구간 타임라인 표시
6. 전체 자막 클릭 탐색
7. 후보 카드 클릭 → 해당 구간으로 즉시 이동
8. 수동 start/end 지정
9. 선택 구간을 바로 쇼츠 MP4로 렌더링
10. 수정 패턴을 저장해 다음 추천에 반영

## 가장 빠른 데모

### CLI 데모
```bash
sermon-shorts demo ./demo-output
```

### 웹 데모
```bash
curl -X POST http://127.0.0.1:8787/api/demo
```

## YouTube 링크로 바로 시작

```bash
sermon-shorts prepare-youtube "https://www.youtube.com/watch?v=VIDEO_ID" \
  --out ./yt-work \
  --cookies-from-browser chrome
sermon-shorts analyze-workspace ./yt-work --out ./yt-work/analysis
sermon-shorts preview --video ./yt-work/source.mp4 --candidates ./yt-work/analysis/candidates.json --out ./yt-work/previews --top 3
```

그 다음 preview MP3를 먼저 들어보고, 마음에 드는 후보만 실제 쇼츠로 렌더링하면 됩니다.

> 참고: YouTube는 클라우드 서버 IP를 자주 막습니다. 이 경우 transcript/download 단계에서 막힐 수 있으니, **로컬 맥/PC에서 웹 스튜디오를 실행하는 방식(A안)** 이 가장 안정적입니다.

```bash
sermon-shorts render \
  --video ./yt-work/source.mp4 \
  --candidates ./yt-work/analysis/candidates.json \
  --out ./yt-work/rendered \
  --top 2
```

## 실제 MP4 파일도 같은 방식으로 처리

웹 스튜디오에서는 MP4 업로드 후 자동 전사를 수행합니다.

- 입력: `source.mp4`
- 출력:
  - `transcript.json`
  - `transcript.vtt`
  - `analysis/candidates.json`
  - `clips/<선택구간>.mp4`
  - `clips/<선택구간>.srt`
  - `clips/<선택구간>.vtt`

즉 **YouTube든 MP4든 최종 UX는 동일**합니다.
- 타임라인 보기
- 자막 보기
- 후보 구간 클릭
- 수동 구간 조정
- 쇼츠 추출

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

### 3) 후보 구간 미리듣기

```bash
sermon-shorts preview \
  --video /path/to/sermon.mp4 \
  --candidates ./shorts-analysis/candidates.json \
  --out ./shorts-analysis/previews \
  --top 3
```

### 4) 실제 쇼츠 렌더링

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
- 저자 의도 / 선호 카테고리 / 필수 키워드와의 일치
- 이전 선택 패턴(카테고리 선호, 평균 길이, 자주 남긴 메모 키워드)

## 학습 방식

현재 버전의 학습은 **가벼운 preference learning** 입니다.

- 후보를 그대로 선택했는지
- 앞을 몇 초 당겼는지 / 뒤를 몇 초 줄였는지
- 어떤 메모를 남겼는지
- 어떤 카테고리를 자주 택하는지

를 `feedback_events.json`, `learning_summary.json` 에 저장하고 다음 추천 점수에 반영합니다.

그리고 그 요약을 바탕으로 `author_profile.json` 을 자동 생성합니다.

- 저자의 대표 선호 카테고리
- 시그니처 키워드
- 평균 선택 길이
- 편집 성향(도입을 더 당기는지, 마무리를 더 자르는지)
- 다음 추천 시 사용할 설명 템플릿

즉, 완전한 ML 모델은 아니지만 **저자의 의도에 맞춘 재정렬 레이어 + 설명 가능한 author profile** 은 이미 들어가 있습니다.

## 현재 구현 범위

구현됨:
- 쇼츠 후보 자동 선별
- YouTube 링크 입력
- MP4 업로드 자동 전사
- 후보 타임라인 리포트
- 후보 MP3 preview 생성
- 웹 스튜디오에서 자막/타임라인 탐색
- 수동 구간 선택 및 세로형 클립 렌더링
- 후보별 자막 SRT/VTT 생성
- 업로드용 제목/설명/해시태그 초안 생성

아직 미구현:
- YouTube OAuth 업로드
- fancy 자막 디자인(색 강조, 애니메이션)
- 다중 얼굴 추적 기반 스마트 크롭

## 테스트

```bash
python -m unittest discover -s tests -v
```

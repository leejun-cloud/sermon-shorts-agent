from __future__ import annotations

import argparse
import shutil
import uuid
from pathlib import Path
from typing import Dict, List

from flask import Flask, jsonify, request, send_from_directory

from .demo import build_demo
from .models import Segment
from .pipeline import analyze_workspace
from .render import extract_range
from .transcript import load_transcript
from .transcribe import transcribe_video
from .utils import ensure_dir, format_ts, read_json, write_json
from .youtube import prepare_youtube


HTML = r'''<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>sermon-shorts timeline studio</title>
  <style>
    :root { color-scheme: dark; }
    body { margin:0; font-family: Inter, Pretendard, system-ui, sans-serif; background:#0b1020; color:#eef2ff; }
    .wrap { max-width: 1400px; margin: 0 auto; padding: 20px; }
    h1 { margin: 0 0 6px; font-size: 28px; }
    .muted { color:#9fb0d6; }
    .grid { display:grid; grid-template-columns: 360px 1fr; gap: 18px; margin-top: 18px; }
    .card { background:#121933; border:1px solid #26325f; border-radius:16px; padding:16px; box-shadow: 0 10px 30px rgba(0,0,0,.2); }
    input, button, textarea { width:100%; box-sizing:border-box; border-radius:10px; border:1px solid #32406f; background:#0c1430; color:#eef2ff; padding:10px 12px; }
    button { cursor:pointer; font-weight:600; background:#3858ff; border:none; }
    button.secondary { background:#1b2548; }
    button.ghost { background:transparent; border:1px solid #32406f; }
    .stack { display:flex; flex-direction:column; gap:10px; }
    .row { display:flex; gap:8px; }
    .row > * { flex:1; }
    .player { width:100%; max-height: 72vh; background:black; border-radius:14px; }
    .candidate { padding:12px; border:1px solid #2a3560; border-radius:14px; margin-bottom:10px; background:#0d1532; }
    .candidate.active { border-color:#6e8cff; background:#111d45; }
    .candidate h3 { margin:0 0 6px; font-size:17px; }
    .pill { display:inline-block; padding:3px 8px; border-radius:999px; font-size:12px; background:#1d2b56; color:#c9d6ff; margin-right:6px; }
    .timeline { position:relative; height:16px; background:#0a1127; border-radius:999px; overflow:hidden; margin:10px 0; border:1px solid #27345f; }
    .timeline span { position:absolute; top:0; bottom:0; border-radius:999px; background:#5776ff; opacity:.9; }
    .transcript-line { padding:8px 10px; border-radius:10px; cursor:pointer; margin-bottom:6px; background:#0d1430; border:1px solid #202d58; }
    .transcript-line:hover { background:#111d45; }
    .transcript-line.active { border-color:#6e8cff; background:#17255a; }
    .small { font-size:12px; color:#99abd3; }
    .status { white-space:pre-wrap; min-height:40px; color:#b8c7ec; }
    .links a { color:#9ec3ff; text-decoration:none; margin-right:12px; }
    @media (max-width: 980px) { .grid { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
<div class="wrap">
  <h1>sermon-shorts timeline studio</h1>
  <div class="muted">유튜브 링크 또는 실제 MP4 파일을 넣으면, 타임라인 + 자막 + 추천 구간 + 수동 구간지정을 한 화면에서 다룹니다.</div>
  <div class="grid">
    <div class="stack">
      <div class="card stack">
        <strong>YouTube 링크</strong>
        <input id="ytUrl" placeholder="https://www.youtube.com/watch?v=..." />
        <div class="small">A안 기준: 로컬 맥/PC에서 실행할수록 유튜브 차단 문제가 적습니다.</div>
        <button id="ytAnalyze">유튜브 분석</button>
      </div>
      <div class="card stack">
        <strong>실제 MP4 파일</strong>
        <input id="videoFile" type="file" accept="video/mp4,video/quicktime,video/*" />
        <div class="row">
          <input id="language" value="ko" placeholder="ko / en / auto" />
          <input id="modelSize" value="tiny" placeholder="tiny / base" />
        </div>
        <button id="uploadAnalyze">MP4 업로드 후 분석</button>
      </div>
      <div class="card stack">
        <strong>빠른 데모</strong>
        <button class="secondary" id="loadDemo">데모 세션 만들기</button>
        <div class="status" id="status">대기 중</div>
      </div>
      <div class="card stack">
        <strong>수동 구간 지정</strong>
        <div class="row">
          <input id="manualStart" type="number" step="0.1" min="0" placeholder="start sec" />
          <input id="manualEnd" type="number" step="0.1" min="0" placeholder="end sec" />
        </div>
        <div class="row">
          <button class="ghost" id="setStart">현재 위치 = 시작</button>
          <button class="ghost" id="setEnd">현재 위치 = 끝</button>
        </div>
        <input id="manualTitle" placeholder="예: 핵심메시지-직접선택" />
        <button id="renderManual">이 구간으로 쇼츠 만들기</button>
        <div class="links" id="renderLinks"></div>
      </div>
    </div>

    <div class="stack">
      <div class="card stack">
        <div><strong id="sessionTitle">세션 없음</strong></div>
        <div class="small" id="sessionMeta">영상 없음</div>
        <video id="video" class="player" controls playsinline></video>
        <div class="timeline" id="timeline"></div>
      </div>
      <div class="card">
        <strong>추천 구간</strong>
        <div id="candidates"></div>
      </div>
      <div class="card">
        <strong>전체 자막 타임라인</strong>
        <div id="transcript"></div>
      </div>
    </div>
  </div>
</div>
<script>
let currentSession = null;
let activeCandidate = null;
const video = document.getElementById('video');

function setStatus(text){ document.getElementById('status').textContent = text; }
function fmt(sec){ sec = Math.max(0, Math.floor(sec || 0)); const h = String(Math.floor(sec/3600)).padStart(2,'0'); const m = String(Math.floor((sec%3600)/60)).padStart(2,'0'); const s = String(sec%60).padStart(2,'0'); return `${h}:${m}:${s}`; }

async function postJSON(url, body){
  const res = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
  const data = await res.json();
  if(!res.ok) throw new Error(data.error || 'request failed');
  return data;
}

async function postForm(url, formData){
  const res = await fetch(url, {method:'POST', body: formData});
  const data = await res.json();
  if(!res.ok) throw new Error(data.error || 'request failed');
  return data;
}

function renderSession(data){
  currentSession = data;
  activeCandidate = null;
  document.getElementById('sessionTitle').textContent = data.title || '제목 없음';
  document.getElementById('sessionMeta').textContent = `${data.source_type} · ${data.duration_label || '-'} · 후보 ${data.candidates.length}개`;
  if(data.video_url){
    video.src = data.video_url;
    const oldTrack = video.querySelector('track');
    if(oldTrack) oldTrack.remove();
    if(data.transcript_vtt_url){
      const track = document.createElement('track');
      track.kind = 'subtitles';
      track.label = 'Transcript';
      track.srclang = 'ko';
      track.src = data.transcript_vtt_url;
      track.default = true;
      video.appendChild(track);
    }
  }
  document.getElementById('manualStart').value = '';
  document.getElementById('manualEnd').value = '';
  renderTimeline(data.candidates, data.duration_seconds || 1);
  renderCandidates(data.candidates);
  renderTranscript(data.transcript);
  document.getElementById('renderLinks').innerHTML = '';
}

function renderTimeline(candidates, duration){
  const el = document.getElementById('timeline');
  el.innerHTML = '';
  for(const c of candidates){
    const span = document.createElement('span');
    span.style.left = `${(c.start / duration) * 100}%`;
    span.style.width = `${Math.max(1, ((c.end - c.start) / duration) * 100)}%`;
    span.title = `${c.title} (${fmt(c.start)}-${fmt(c.end)})`;
    span.onclick = () => selectCandidate(c.rank);
    el.appendChild(span);
  }
}

function renderCandidates(candidates){
  const root = document.getElementById('candidates');
  root.innerHTML = '';
  for(const c of candidates){
    const div = document.createElement('div');
    div.className = 'candidate';
    div.id = `candidate-${c.rank}`;
    div.innerHTML = `
      <div class="small">#${c.rank} · ${fmt(c.start)} ~ ${fmt(c.end)} · ${Math.round(c.end-c.start)}초</div>
      <h3>${c.title}</h3>
      <div><span class="pill">${c.category}</span><span class="pill">score ${c.score}</span></div>
      <p>${c.summary}</p>
      <div class="small">${(c.reasons||[]).join(' · ')}</div>
      <div class="row" style="margin-top:10px;">
        <button data-rank="${c.rank}" class="jumpBtn">여기로 이동</button>
        <button data-rank="${c.rank}" class="clipBtn secondary">이 후보 추출</button>
      </div>
    `;
    root.appendChild(div);
  }
  root.querySelectorAll('.jumpBtn').forEach(btn => btn.onclick = () => selectCandidate(Number(btn.dataset.rank)));
  root.querySelectorAll('.clipBtn').forEach(btn => btn.onclick = () => renderCandidate(Number(btn.dataset.rank)));
}

function renderTranscript(lines){
  const root = document.getElementById('transcript');
  root.innerHTML = '';
  for(const line of lines){
    const div = document.createElement('div');
    div.className = 'transcript-line';
    div.dataset.start = line.start;
    div.dataset.end = line.end;
    div.innerHTML = `<div class="small">${fmt(line.start)} ~ ${fmt(line.end)}</div><div>${line.text}</div>`;
    div.onclick = () => { video.currentTime = line.start; video.play(); highlightTranscript(line.start); };
    root.appendChild(div);
  }
}

function highlightTranscript(current){
  document.querySelectorAll('.transcript-line').forEach(el => {
    const start = Number(el.dataset.start);
    const end = Number(el.dataset.end);
    el.classList.toggle('active', current >= start && current <= end);
  });
}

function selectCandidate(rank){
  if(!currentSession) return;
  const candidate = currentSession.candidates.find(c => c.rank === rank);
  if(!candidate) return;
  activeCandidate = candidate;
  document.querySelectorAll('.candidate').forEach(el => el.classList.remove('active'));
  const box = document.getElementById(`candidate-${rank}`);
  if(box) box.classList.add('active');
  document.getElementById('manualStart').value = candidate.start;
  document.getElementById('manualEnd').value = candidate.end;
  document.getElementById('manualTitle').value = candidate.title;
  video.currentTime = candidate.start;
  video.play();
}

async function renderCandidate(rank){
  if(!currentSession) return;
  setStatus('후보 구간 렌더링 중...');
  try {
    const data = await postJSON(`/api/session/${currentSession.session_id}/render-candidate`, {rank});
    setRenderLinks(data);
    setStatus('후보 추출 완료');
  } catch (err) {
    setStatus('오류: ' + err.message);
  }
}

function setRenderLinks(data){
  const root = document.getElementById('renderLinks');
  root.innerHTML = `
    <a href="${data.video_url}" target="_blank">MP4 보기</a>
    <a href="${data.srt_url}" target="_blank">SRT</a>
    <a href="${data.vtt_url}" target="_blank">VTT</a>
  `;
}

document.getElementById('ytAnalyze').onclick = async () => {
  const url = document.getElementById('ytUrl').value.trim();
  if(!url) return setStatus('유튜브 링크를 넣어주세요.');
  setStatus('유튜브 분석 중... 로컬에서는 잘 되지만 서버 IP에 따라 차단될 수 있습니다.');
  try {
    const data = await postJSON('/api/analyze-youtube', {url});
    renderSession(data);
    setStatus('유튜브 분석 완료');
  } catch (err) {
    setStatus('오류: ' + err.message);
  }
};

document.getElementById('uploadAnalyze').onclick = async () => {
  const file = document.getElementById('videoFile').files[0];
  if(!file) return setStatus('MP4 파일을 선택해주세요.');
  const form = new FormData();
  form.append('video', file);
  form.append('language', document.getElementById('language').value.trim());
  form.append('model_size', document.getElementById('modelSize').value.trim());
  setStatus('MP4 업로드 및 전사/분석 중... 처음에는 모델 다운로드 때문에 조금 걸릴 수 있습니다.');
  try {
    const data = await postForm('/api/analyze-upload', form);
    renderSession(data);
    setStatus('MP4 분석 완료');
  } catch (err) {
    setStatus('오류: ' + err.message);
  }
};

document.getElementById('loadDemo').onclick = async () => {
  setStatus('데모 세션 생성 중...');
  try {
    const data = await postJSON('/api/demo', {});
    renderSession(data);
    setStatus('데모 로드 완료');
  } catch (err) {
    setStatus('오류: ' + err.message);
  }
};

document.getElementById('setStart').onclick = () => { document.getElementById('manualStart').value = video.currentTime.toFixed(1); };

document.getElementById('setEnd').onclick = () => { document.getElementById('manualEnd').value = video.currentTime.toFixed(1); };

document.getElementById('renderManual').onclick = async () => {
  if(!currentSession) return setStatus('먼저 세션을 생성하세요.');
  const start = Number(document.getElementById('manualStart').value);
  const end = Number(document.getElementById('manualEnd').value);
  const title = document.getElementById('manualTitle').value.trim() || 'manual-range';
  if(!(end > start)) return setStatus('끝 시간이 시작 시간보다 커야 합니다.');
  setStatus('선택 구간 렌더링 중...');
  try {
    const data = await postJSON(`/api/session/${currentSession.session_id}/render-range`, {start, end, title});
    setRenderLinks(data);
    setStatus('수동 구간 추출 완료');
  } catch (err) {
    setStatus('오류: ' + err.message);
  }
};

video.addEventListener('timeupdate', () => highlightTranscript(video.currentTime));
</script>
</body>
</html>'''


def create_app(data_root: Path) -> Flask:
    app = Flask(__name__)
    data_root = ensure_dir(data_root)

    @app.get('/')
    def index():
        return HTML

    @app.get('/media/<session_id>/<path:filename>')
    def media(session_id: str, filename: str):
        root = data_root / session_id
        return send_from_directory(root, filename, as_attachment=False)

    @app.get('/api/session/<session_id>')
    def session_payload(session_id: str):
        return jsonify(_load_session_payload(data_root, session_id))

    @app.post('/api/demo')
    def demo():
        session_id = uuid.uuid4().hex[:10]
        root = ensure_dir(data_root / session_id)
        build_demo(root)
        _write_manifest(root, {
            'session_id': session_id,
            'title': 'demo session',
            'source_type': 'demo',
            'video_file': 'demo-video.mp4',
            'transcript_file': 'demo-transcript.json',
            'transcript_vtt_file': None,
            'analysis_dir': '.',
            'youtube_url': None,
        })
        return jsonify(_load_session_payload(data_root, session_id))

    @app.post('/api/analyze-upload')
    def analyze_upload():
        file = request.files.get('video')
        if not file or not file.filename:
            return jsonify({'error': 'video file is required'}), 400
        session_id = uuid.uuid4().hex[:10]
        root = ensure_dir(data_root / session_id)
        ext = Path(file.filename).suffix or '.mp4'
        video_path = root / f'source{ext}'
        file.save(video_path)
        language = (request.form.get('language') or 'ko').strip() or None
        if language == 'auto':
            language = None
        model_size = (request.form.get('model_size') or 'tiny').strip() or 'tiny'
        transcribe_video(video_path, root, model_size=model_size, language=language)
        analyze_workspace(root, root / 'analysis', top_n=5)
        _write_manifest(root, {
            'session_id': session_id,
            'title': video_path.name,
            'source_type': 'upload',
            'video_file': video_path.name,
            'transcript_file': 'transcript.json',
            'transcript_vtt_file': 'transcript.vtt',
            'analysis_dir': 'analysis',
            'youtube_url': None,
        })
        return jsonify(_load_session_payload(data_root, session_id))

    @app.post('/api/analyze-youtube')
    def analyze_youtube():
        payload = request.get_json(force=True, silent=True) or {}
        url = (payload.get('url') or '').strip()
        if not url:
            return jsonify({'error': 'url is required'}), 400
        session_id = uuid.uuid4().hex[:10]
        root = ensure_dir(data_root / session_id)
        try:
            result = prepare_youtube(url, root, languages=['ko', 'en'], download=True)
        except Exception as exc:
            return jsonify({'error': f'YouTube 준비 실패: {exc}'}), 400
        transcript_path = Path(result['transcript_path'])
        if transcript_path.name != 'transcript.json':
            shutil.copy2(transcript_path, root / 'transcript.json')
        segments = load_transcript(root / 'transcript.json')
        from .utils import write_webvtt
        write_webvtt(root / 'transcript.vtt', segments)
        analyze_workspace(root, root / 'analysis', top_n=5)
        _write_manifest(root, {
            'session_id': session_id,
            'title': result.get('title') or 'youtube',
            'source_type': 'youtube',
            'video_file': Path(result['video_path']).name if result.get('video_path') else None,
            'transcript_file': 'transcript.json',
            'transcript_vtt_file': 'transcript.vtt',
            'analysis_dir': 'analysis',
            'youtube_url': url,
        })
        return jsonify(_load_session_payload(data_root, session_id))

    @app.post('/api/session/<session_id>/render-candidate')
    def render_candidate(session_id: str):
        payload = request.get_json(force=True, silent=True) or {}
        rank = int(payload.get('rank', 0))
        data = _load_session_payload(data_root, session_id)
        candidates = data['candidates']
        candidate = next((item for item in candidates if item['rank'] == rank), None)
        if not candidate:
            return jsonify({'error': 'candidate not found'}), 404
        return jsonify(_render_range(data_root, session_id, candidate['start'], candidate['end'], candidate['title']))

    @app.post('/api/session/<session_id>/render-range')
    def render_range(session_id: str):
        payload = request.get_json(force=True, silent=True) or {}
        start = float(payload.get('start', 0))
        end = float(payload.get('end', 0))
        title = (payload.get('title') or 'manual-range').strip()
        if end <= start:
            return jsonify({'error': 'end must be greater than start'}), 400
        return jsonify(_render_range(data_root, session_id, start, end, title))

    return app


def _manifest_path(root: Path) -> Path:
    return root / 'session.json'


def _write_manifest(root: Path, payload: Dict) -> None:
    write_json(_manifest_path(root), payload)


def _load_session_payload(data_root: Path, session_id: str) -> Dict:
    root = data_root / session_id
    manifest = read_json(_manifest_path(root))
    analysis_dir = root / manifest.get('analysis_dir', 'analysis')
    transcript_path = root / manifest['transcript_file']
    transcript = load_transcript(transcript_path)
    candidates = read_json(analysis_dir / 'candidates.json')
    return {
        'session_id': session_id,
        'title': manifest.get('title'),
        'source_type': manifest.get('source_type'),
        'youtube_url': manifest.get('youtube_url'),
        'video_url': f"/media/{session_id}/{manifest['video_file']}" if manifest.get('video_file') else None,
        'transcript_vtt_url': f"/media/{session_id}/{manifest['transcript_vtt_file']}" if manifest.get('transcript_vtt_file') else None,
        'duration_seconds': _duration_seconds(transcript),
        'duration_label': format_ts(_duration_seconds(transcript)),
        'transcript': [{'start': s.start, 'end': s.end, 'text': s.text} for s in transcript],
        'candidates': candidates,
    }


def _duration_seconds(segments: List[Segment]) -> float:
    return max((s.end for s in segments), default=0.0)


def _render_range(data_root: Path, session_id: str, start: float, end: float, title: str) -> Dict:
    root = data_root / session_id
    manifest = read_json(_manifest_path(root))
    if not manifest.get('video_file'):
        raise FileNotFoundError('video file not available for this session')
    video_path = root / manifest['video_file']
    transcript = load_transcript(root / manifest['transcript_file'])
    clip_root = ensure_dir(root / 'clips')
    result = extract_range(video_path, clip_root, start=start, end=end, title=title, segments=transcript)
    result_path = Path(result['video'])
    return {
        'video_url': f"/media/{session_id}/{result_path.relative_to(root)}",
        'srt_url': f"/media/{session_id}/{Path(result['srt']).relative_to(root)}",
        'vtt_url': f"/media/{session_id}/{Path(result['vtt']).relative_to(root)}",
        'start': start,
        'end': end,
        'duration': result['duration'],
        'title': title,
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog='sermon-shorts-web')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8787)
    parser.add_argument('--data-root', type=Path, default=Path('/tmp/sermon-shorts-web'))
    args = parser.parse_args()
    app = create_app(args.data_root)
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == '__main__':
    main()

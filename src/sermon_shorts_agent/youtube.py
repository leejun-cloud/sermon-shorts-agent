from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from .utils import ensure_dir, write_json


def extract_video_id(value: str) -> str:
    value = value.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        return value
    patterns = [
        r"v=([A-Za-z0-9_-]{11})",
        r"youtu\.be/([A-Za-z0-9_-]{11})",
        r"/shorts/([A-Za-z0-9_-]{11})",
        r"/embed/([A-Za-z0-9_-]{11})",
        r"/live/([A-Za-z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, value)
        if match:
            return match.group(1)
    raise ValueError(f"could not extract YouTube video id from: {value}")


def _apply_cookie_options(opts: Dict, cookies_from_browser: Optional[str] = None, cookies_path: Optional[str] = None) -> Dict:
    opts = dict(opts)
    browser = str(cookies_from_browser or '').strip()
    cookie_file = str(cookies_path or '').strip()
    if browser and browser.lower() != 'none':
        opts['cookiesfrombrowser'] = (browser,)
    if cookie_file:
        opts['cookiefile'] = cookie_file
    return opts


def fetch_transcript(url_or_id: str, languages: Optional[List[str]] = None, *, cookies_from_browser: Optional[str] = None, cookies_path: Optional[str] = None) -> List[Dict]:
    from youtube_transcript_api import YouTubeTranscriptApi

    video_id = extract_video_id(url_or_id)
    languages = languages or ["ko", "en"]
    api = YouTubeTranscriptApi()
    try:
        transcript = api.fetch(video_id, languages=languages)
        normalized = []
        for item in transcript:
            start = float(item.start)
            duration = float(item.duration or 0.0)
            text = str(item.text or "").replace("\n", " ").strip()
            if not text:
                continue
            normalized.append({
                "start": round(start, 3),
                "end": round(start + max(0.2, duration), 3),
                "text": text,
            })
        if normalized:
            return normalized
    except Exception:
        pass
    return _fetch_transcript_via_ytdlp(
        url_or_id,
        languages,
        cookies_from_browser=cookies_from_browser,
        cookies_path=cookies_path,
    )


def _fetch_transcript_via_ytdlp(url_or_id: str, languages: List[str], *, cookies_from_browser: Optional[str] = None, cookies_path: Optional[str] = None) -> List[Dict]:
    from yt_dlp import YoutubeDL

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        outtmpl = str(root / "captions")
        langs = []
        for lang in languages:
            langs.extend([lang, f"{lang}.*"])
        opts = _apply_cookie_options({
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "writeautomaticsub": True,
            "writesubtitles": True,
            "subtitleslangs": langs,
            "subtitlesformat": "vtt",
            "outtmpl": outtmpl,
        }, cookies_from_browser=cookies_from_browser, cookies_path=cookies_path)
        with YoutubeDL(opts) as ydl:
            ydl.download([url_or_id])
        vtts = sorted(root.glob("captions*.vtt"))
        if not vtts:
            raise RuntimeError("could not fetch transcript from YouTube: transcript api blocked and yt-dlp subtitle fallback unavailable")
        return _parse_vtt(vtts[0])


def _parse_vtt(path: Path) -> List[Dict]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    blocks = re.split(r"\n\s*\n", text)
    rows = []
    seen = set()
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines or lines[0] == "WEBVTT" or lines[0].startswith("NOTE"):
            continue
        timing_index = 0
        if "-->" not in lines[0] and len(lines) > 1:
            timing_index = 1
        if timing_index >= len(lines) or "-->" not in lines[timing_index]:
            continue
        start_s, end_s = [part.strip().split(" ")[0] for part in lines[timing_index].split("-->")]
        payload = " ".join(lines[timing_index + 1:]).strip()
        payload = re.sub(r"<[^>]+>", "", payload)
        payload = re.sub(r"\s+", " ", payload)
        if not payload:
            continue
        start = _parse_vtt_ts(start_s)
        end = _parse_vtt_ts(end_s)
        key = (round(start, 3), round(end, 3), payload)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "start": round(start, 3),
            "end": round(end, 3),
            "text": payload,
        })
    if not rows:
        raise RuntimeError(f"failed to parse subtitle file: {path}")
    return rows


def _parse_vtt_ts(value: str) -> float:
    value = value.replace(",", ".")
    parts = value.split(":")
    if len(parts) == 3:
        h, m, s = parts
    elif len(parts) == 2:
        h = 0
        m, s = parts
    else:
        raise ValueError(f"invalid VTT timestamp: {value}")
    return int(h) * 3600 + int(m) * 60 + float(s)


def fetch_metadata(url: str, *, cookies_from_browser: Optional[str] = None, cookies_path: Optional[str] = None) -> Dict:
    from yt_dlp import YoutubeDL

    opts = _apply_cookie_options({"quiet": True, "no_warnings": True, "skip_download": True}, cookies_from_browser=cookies_from_browser, cookies_path=cookies_path)
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return {
        "id": info.get("id"),
        "title": info.get("title"),
        "uploader": info.get("uploader") or info.get("channel"),
        "duration": info.get("duration"),
        "webpage_url": info.get("webpage_url") or url,
        "thumbnail": info.get("thumbnail"),
        "description": info.get("description"),
    }


def download_video(url: str, out_dir: Path, *, cookies_from_browser: Optional[str] = None, cookies_path: Optional[str] = None) -> Path:
    from yt_dlp import YoutubeDL

    ensure_dir(out_dir)
    outtmpl = str(out_dir / "source.%(ext)s")
    opts = _apply_cookie_options({
        "quiet": True,
        "no_warnings": True,
        "outtmpl": outtmpl,
        "format": "mp4/bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "restrictfilenames": False,
    }, cookies_from_browser=cookies_from_browser, cookies_path=cookies_path)
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = Path(ydl.prepare_filename(info))
    if path.suffix.lower() != ".mp4":
        mp4 = path.with_suffix(".mp4")
        if mp4.exists():
            path = mp4
    if not path.exists():
        matches = sorted(out_dir.glob("source.*"))
        if not matches:
            raise FileNotFoundError("yt-dlp did not produce a downloadable media file")
        path = matches[0]
    return path


def prepare_youtube(url: str, out_dir: Path, languages: Optional[List[str]] = None, download: bool = True, *, cookies_from_browser: Optional[str] = None, cookies_path: Optional[str] = None) -> Dict:
    ensure_dir(out_dir)
    transcript = fetch_transcript(url, languages=languages, cookies_from_browser=cookies_from_browser, cookies_path=cookies_path)
    transcript_path = out_dir / "transcript.json"
    write_json(transcript_path, transcript)
    metadata = fetch_metadata(url, cookies_from_browser=cookies_from_browser, cookies_path=cookies_path)
    write_json(out_dir / "youtube_metadata.json", metadata)
    video_path = None
    if download:
        video_path = download_video(url, out_dir, cookies_from_browser=cookies_from_browser, cookies_path=cookies_path)
    result = {
        "transcript_path": str(transcript_path),
        "metadata_path": str(out_dir / "youtube_metadata.json"),
        "video_path": str(video_path) if video_path else None,
        "title": metadata.get("title"),
        "url": metadata.get("webpage_url") or url,
        "cookies_from_browser": cookies_from_browser or '',
        "cookies_path": cookies_path or '',
    }
    write_json(out_dir / "prepare_result.json", result)
    return result

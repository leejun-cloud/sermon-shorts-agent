import json
import tempfile
import unittest
from pathlib import Path

from sermon_shorts_agent.pipeline import analyze
from sermon_shorts_agent.webapp import create_app
from sermon_shorts_agent.youtube import extract_video_id


class PipelineTests(unittest.TestCase):
    def test_analyze_picks_candidates_under_sixty_seconds(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            transcript = [
                {"start": 0.0, "end": 8.0, "text": "오늘 하나님이 우리에게 주시는 말씀을 보겠습니다."},
                {"start": 8.0, "end": 16.0, "text": "문제보다 말씀이 더 큽니다. 이것이 핵심 메시지입니다."},
                {"start": 16.0, "end": 24.0, "text": "반드시 다시 일어나야 합니다! 포기하지 마십시오!"},
                {"start": 24.0, "end": 34.0, "text": "이번 주에 한 가지 실천을 적고 순종으로 나아가십시오."},
                {"start": 34.0, "end": 46.0, "text": "누가복음 8장에서 예수님은 두려움 가운데 찾아오십니다."}
            ]
            highlights = [{"start": 14.0, "end": 22.0, "score": 6.0, "peak_db": -2.0}]
            transcript_path = root / 'transcript.json'
            highlights_path = root / 'highlights.json'
            transcript_path.write_text(json.dumps(transcript, ensure_ascii=False), encoding='utf-8')
            highlights_path.write_text(json.dumps(highlights, ensure_ascii=False), encoding='utf-8')
            out = root / 'out'
            candidates = analyze(transcript_path, highlights_path, out, top_n=3)
            self.assertGreaterEqual(len(candidates), 1)
            top = candidates[0]
            self.assertLessEqual(top.end - top.start, 59.0)
            self.assertIn(top.category, {'message', 'emotion', 'application', 'scripture'})
            self.assertTrue((out / 'candidates.json').exists())
            self.assertTrue((out / 'report.md').exists())

    def test_extract_video_id_from_common_urls(self):
        self.assertEqual(extract_video_id('https://www.youtube.com/watch?v=jNQXAC9IVRw'), 'jNQXAC9IVRw')
        self.assertEqual(extract_video_id('https://youtu.be/jNQXAC9IVRw?si=abc'), 'jNQXAC9IVRw')
        self.assertEqual(extract_video_id('jNQXAC9IVRw'), 'jNQXAC9IVRw')

    def test_webapp_demo_and_manual_render(self):
        with tempfile.TemporaryDirectory() as td:
            app = create_app(Path(td))
            client = app.test_client()
            resp = client.post('/api/demo', json={})
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertIn('session_id', data)
            self.assertGreaterEqual(len(data['candidates']), 1)
            render = client.post(
                f"/api/session/{data['session_id']}/render-range",
                json={'start': 15, 'end': 35, 'title': 'manual-test'}
            )
            self.assertEqual(render.status_code, 200)
            render_data = render.get_json()
            self.assertIn('/media/', render_data['video_url'])
            self.assertIn('/media/', render_data['srt_url'])


if __name__ == '__main__':
    unittest.main()

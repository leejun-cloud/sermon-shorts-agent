import json
import tempfile
import unittest
from pathlib import Path

from sermon_shorts_agent.pipeline import analyze


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


if __name__ == '__main__':
    unittest.main()

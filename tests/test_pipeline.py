import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sermon_shorts_agent.pipeline import analyze
from sermon_shorts_agent.webapp import create_app
from sermon_shorts_agent.youtube import extract_video_id
from sermon_shorts_agent.learning import analyze_learning_topic
from sermon_shorts_agent.exporters import export_learning_to_obsidian, export_learning_to_notion


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
            candidates = analyze(
                transcript_path,
                highlights_path,
                out,
                top_n=3,
                preferences={'preferred_categories': ['application'], 'must_include_keywords': ['실천']}
            )
            self.assertGreaterEqual(len(candidates), 1)
            top = candidates[0]
            self.assertLessEqual(top.end - top.start, 59.0)
            self.assertIn(top.category, {'message', 'emotion', 'application', 'scripture'})
            self.assertTrue((out / 'candidates.json').exists())
            self.assertTrue((out / 'report.md').exists())
            self.assertTrue(any('저자 선호 카테고리와 일치' in reason or '필수 키워드 포함' in reason for reason in top.reasons))
            self.assertTrue(top.match_summary)
            self.assertGreaterEqual(len(top.score_breakdown), 1)

    def test_extract_video_id_from_common_urls(self):
        self.assertEqual(extract_video_id('https://www.youtube.com/watch?v=jNQXAC9IVRw'), 'jNQXAC9IVRw')
        self.assertEqual(extract_video_id('https://youtu.be/jNQXAC9IVRw?si=abc'), 'jNQXAC9IVRw')
        self.assertEqual(extract_video_id('jNQXAC9IVRw'), 'jNQXAC9IVRw')

    def test_webapp_demo_and_manual_render(self):
        with tempfile.TemporaryDirectory() as td:
            app = create_app(Path(td))
            client = app.test_client()
            prefs = {
                'preferred_categories': 'message,application',
                'must_include_keywords': '실천,순종',
                'author_intent': '짧지만 적용이 살아야 한다',
                'learning_enabled': True,
            }
            save = client.post('/api/preferences', json=prefs)
            self.assertEqual(save.status_code, 200)
            resp = client.post('/api/demo', json={'preferences': prefs})
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertIn('session_id', data)
            self.assertIn('author_profile', data)
            self.assertTrue(data['author_profile']['headline'])
            self.assertGreaterEqual(len(data['candidates']), 1)
            render = client.post(
                f"/api/session/{data['session_id']}/render-range",
                json={'start': 15, 'end': 35, 'title': 'manual-test', 'note': '앞부분을 조금 덜어냄', 'preferences': prefs}
            )
            self.assertEqual(render.status_code, 200)
            render_data = render.get_json()
            self.assertIn('/media/', render_data['video_url'])
            self.assertIn('/media/', render_data['srt_url'])
            self.assertIn('learning', render_data)
            self.assertIn('author_profile', render_data)
            prefs_get = client.get('/api/preferences')
            self.assertEqual(prefs_get.status_code, 200)
            pref_payload = prefs_get.get_json()
            self.assertIn('preferences', pref_payload)
            self.assertIn('author_profile', pref_payload)
            self.assertGreaterEqual(pref_payload['learning']['total_events'], 1)

    @patch('sermon_shorts_agent.learning.fetch_metadata')
    @patch('sermon_shorts_agent.learning.fetch_transcript')
    @patch('sermon_shorts_agent.learning.search_youtube_topic')
    def test_learning_topic_analysis_builds_results(self, mock_search, mock_transcript, mock_metadata):
        mock_search.return_value = [
            {'id': 'aaa111bbb22', 'title': '바이브 코딩 입문', 'url': 'https://www.youtube.com/watch?v=aaa111bbb22', 'uploader': '채널A', 'duration': 600, 'description': 'desc'},
        ]
        mock_metadata.return_value = {'id': 'aaa111bbb22', 'title': '바이브 코딩 입문', 'uploader': '채널A', 'duration': 600, 'webpage_url': 'https://www.youtube.com/watch?v=aaa111bbb22', 'description': 'desc'}
        mock_transcript.return_value = [
            {'start': 0.0, 'end': 8.0, 'text': '바이브 코딩의 핵심 개념을 설명합니다.'},
            {'start': 8.0, 'end': 18.0, 'text': '실전 예시로 프롬프트를 어떻게 쓰는지 보여줍니다.'},
            {'start': 18.0, 'end': 28.0, 'text': '직접 따라해볼 수 있는 단계별 방법을 알려줍니다.'},
        ]
        with tempfile.TemporaryDirectory() as td:
            result = analyze_learning_topic('바이브 코딩', Path(td), limit=1, per_video_top_n=2)
            self.assertEqual(result['topic'], '바이브 코딩')
            self.assertGreaterEqual(result['counts']['videos_analyzed'], 1)
            self.assertGreaterEqual(len(result['top_highlights']), 1)
            self.assertTrue((Path(td) / 'learning_results.json').exists())
            self.assertTrue((Path(td) / 'learning_report.md').exists())
            self.assertIn('recommendation_notes', result['top_highlights'][0])

    def test_obsidian_export_writes_notes(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as vault_td:
            result_root = Path(td)
            payload = {
                'topic': '바이브 코딩',
                'keywords': ['바이브', '코딩'],
                'counts': {'videos_analyzed': 1, 'highlights': 1},
                'videos': [{
                    'title': '바이브 코딩 입문',
                    'url': 'https://www.youtube.com/watch?v=aaa111bbb22',
                    'uploader': '채널A',
                    'duration': 600,
                    'why_video': ['핵심 하이라이트 1개'],
                    'highlights': [{
                        'rank': 1, 'title': '핵심 개념', 'start': 10, 'end': 45, 'duration': 35,
                        'lesson_type': 'concept', 'summary': '핵심 개념 정리', 'recommendation_notes': ['개념 이해에 좋음'], 'excerpt': '설명'
                    }],
                }],
                'top_highlights': [],
            }
            (result_root / 'learning_results.json').write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
            export = export_learning_to_obsidian(result_root, Path(vault_td))
            self.assertEqual(export['note_count'], 1)
            self.assertTrue(Path(export['hub_path']).exists())

    @patch('sermon_shorts_agent.exporters.urllib.request.urlopen')
    def test_notion_export_uses_database_schema(self, mock_urlopen):
        class FakeResponse:
            def __init__(self, data):
                self.data = json.dumps(data).encode('utf-8')
            def read(self):
                return self.data
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False

        schema = {
            'properties': {
                'Name': {'type': 'title'},
                '주제': {'type': 'rich_text'},
                '링크': {'type': 'url'},
                '채널': {'type': 'rich_text'},
                '상태': {'type': 'select'},
                '요약': {'type': 'rich_text'},
            }
        }
        created = {'id': 'page123', 'url': 'https://notion.so/page123'}
        mock_urlopen.side_effect = [FakeResponse(schema), FakeResponse(created)]
        with tempfile.TemporaryDirectory() as td:
            result_root = Path(td)
            payload = {
                'topic': '바이브 코딩',
                'keywords': ['바이브', '코딩'],
                'videos': [{
                    'title': '바이브 코딩 입문',
                    'url': 'https://www.youtube.com/watch?v=aaa111bbb22',
                    'uploader': '채널A',
                    'why_video': ['핵심 하이라이트 1개'],
                    'highlights': [{'start': 10, 'end': 45, 'summary': '핵심 개념', 'recommendation_notes': ['개념 이해에 좋음']}],
                }],
                'top_highlights': [],
            }
            (result_root / 'learning_results.json').write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
            os.environ['NOTION_TOKEN'] = 'secret_test'
            try:
                export = export_learning_to_notion(result_root, 'db123')
            finally:
                os.environ.pop('NOTION_TOKEN', None)
            self.assertEqual(export['created_count'], 1)
            self.assertEqual(export['token_used'], 'NOTION_TOKEN')

    @patch('sermon_shorts_agent.webapp.export_learning_to_notion')
    @patch('sermon_shorts_agent.webapp.export_learning_to_obsidian')
    @patch('sermon_shorts_agent.webapp.analyze_learning_topic')
    def test_learning_api_routes(self, mock_learning, mock_obsidian, mock_notion):
        mock_learning.return_value = {
            'topic': '바이브 코딩',
            'keywords': ['바이브', '코딩'],
            'videos': [{'title': '입문', 'url': 'https://youtube.com/watch?v=1', 'highlights': [], 'top_score': 5.0, 'why_video': []}],
            'top_highlights': [],
            'counts': {'videos_considered': 1, 'videos_analyzed': 1, 'highlights': 0},
        }
        mock_obsidian.return_value = {'hub_path': '/vault/hub.md', 'note_count': 1}
        mock_notion.return_value = {'created_count': 1}
        with tempfile.TemporaryDirectory() as td:
            app = create_app(Path(td))
            client = app.test_client()
            resp = client.post('/api/learning/topic', json={'topic': '바이브 코딩', 'urls': ['https://youtube.com/watch?v=1']})
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data['mode'], 'learning')
            self.assertIn('session_id', data)
            export = client.post(f"/api/learning/{data['session_id']}/export", json={'obsidian_path': '/vault', 'notion_database_id': 'db123'})
            self.assertEqual(export.status_code, 200)
            export_data = export.get_json()
            self.assertIn('obsidian', export_data)
            self.assertIn('notion', export_data)


if __name__ == '__main__':
    unittest.main()

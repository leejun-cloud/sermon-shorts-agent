import argparse
from pathlib import Path

from .demo import build_demo
from .exporters import export_learning_to_notion, export_learning_to_obsidian
from .learning import analyze_learning_topic
from .pipeline import analyze, analyze_workspace
from .render import render_candidates, render_previews
from .youtube import prepare_youtube


def main() -> None:
    parser = argparse.ArgumentParser(prog='sermon-shorts')
    sub = parser.add_subparsers(dest='command', required=True)

    p_analyze = sub.add_parser('analyze', help='Analyze transcript/highlights and write candidates')
    p_analyze.add_argument('transcript', type=Path)
    p_analyze.add_argument('--highlights', type=Path)
    p_analyze.add_argument('--out', type=Path, required=True)
    p_analyze.add_argument('--top-n', type=int, default=5)

    p_workspace = sub.add_parser('analyze-workspace', help='Analyze a timecode-agent workspace')
    p_workspace.add_argument('workspace', type=Path)
    p_workspace.add_argument('--out', type=Path, required=True)
    p_workspace.add_argument('--top-n', type=int, default=5)

    p_prepare = sub.add_parser('prepare-youtube', help='Fetch transcript/metadata/video from a YouTube URL')
    p_prepare.add_argument('url')
    p_prepare.add_argument('--out', type=Path, required=True)
    p_prepare.add_argument('--languages', default='ko,en')
    p_prepare.add_argument('--skip-download', action='store_true')
    p_prepare.add_argument('--cookies-from-browser', default='')
    p_prepare.add_argument('--cookies-path', default='')

    p_preview = sub.add_parser('preview', help='Extract MP3 previews for top candidate ranges')
    p_preview.add_argument('--video', type=Path, required=True)
    p_preview.add_argument('--candidates', type=Path, required=True)
    p_preview.add_argument('--out', type=Path, required=True)
    p_preview.add_argument('--top', type=int, default=3)

    p_render = sub.add_parser('render', help='Render vertical shorts from candidates json')
    p_render.add_argument('--video', type=Path, required=True)
    p_render.add_argument('--candidates', type=Path, required=True)
    p_render.add_argument('--out', type=Path, required=True)
    p_render.add_argument('--top', type=int, default=3)
    p_render.add_argument('--no-burn-subtitles', action='store_true')
    p_render.add_argument('--layout', choices=['auto', 'crop', 'letterbox'], default='auto',
                           help='auto(기본): 원본에 여백이 있으면 letterbox+블러, 없으면 crop. '
                                'crop: 확대/크롭(기존 방식). letterbox: 원본 무손실+블러 배경, 자막은 여백에.')

    p_demo = sub.add_parser('demo', help='Generate demo transcript/video and run end-to-end')
    p_demo.add_argument('out', type=Path)

    p_learn = sub.add_parser('learn-topic', help='Recommend topic-related YouTube videos and extract learning highlights')
    p_learn.add_argument('--topic', required=True)
    p_learn.add_argument('--out', type=Path, required=True)
    p_learn.add_argument('--url', action='append', default=[])
    p_learn.add_argument('--limit', type=int, default=5)
    p_learn.add_argument('--per-video-top-n', type=int, default=3)
    p_learn.add_argument('--no-search-related', action='store_true')

    p_export_obs = sub.add_parser('export-obsidian', help='Export learning results to an Obsidian vault')
    p_export_obs.add_argument('--result-root', type=Path, required=True)
    p_export_obs.add_argument('--vault', type=Path, required=True)
    p_export_obs.add_argument('--subdir', default='03_산출물/강의안/유튜브학습')

    p_export_notion = sub.add_parser('export-notion', help='Export learning results to a Notion database')
    p_export_notion.add_argument('--result-root', type=Path, required=True)
    p_export_notion.add_argument('--database-id', required=True)
    p_export_notion.add_argument('--token', default='')

    args = parser.parse_args()
    if args.command == 'analyze':
        candidates = analyze(args.transcript, args.highlights, args.out, top_n=args.top_n)
        print(f'wrote {len(candidates)} candidates -> {args.out}')
        return
    if args.command == 'analyze-workspace':
        candidates = analyze_workspace(args.workspace, args.out, top_n=args.top_n)
        print(f'wrote {len(candidates)} candidates -> {args.out}')
        return
    if args.command == 'prepare-youtube':
        languages = [item.strip() for item in args.languages.split(',') if item.strip()]
        result = prepare_youtube(
            args.url,
            args.out,
            languages=languages,
            download=not args.skip_download,
            cookies_from_browser=args.cookies_from_browser,
            cookies_path=args.cookies_path,
        )
        print(f"prepared YouTube source -> {result['title']}")
        print(result)
        return
    if args.command == 'preview':
        rendered = render_previews(args.video, args.candidates, args.out, top=args.top)
        print(f'rendered {len(rendered)} preview mp3 files -> {args.out}')
        return
    if args.command == 'render':
        rendered = render_candidates(args.video, args.candidates, args.out, top=args.top,
                                      burn_subtitles=not args.no_burn_subtitles, layout=args.layout)
        print(f'rendered {len(rendered)} clips -> {args.out}')
        return
    if args.command == 'demo':
        out = build_demo(args.out)
        print(f'demo ready -> {out}')
        return
    if args.command == 'learn-topic':
        result = analyze_learning_topic(
            args.topic,
            args.out,
            manual_urls=args.url,
            search_related=not args.no_search_related,
            limit=args.limit,
            per_video_top_n=args.per_video_top_n,
        )
        print(f"learning results ready -> {args.out}")
        print(f"videos={result['counts']['videos_analyzed']}, highlights={result['counts']['highlights']}")
        return
    if args.command == 'export-obsidian':
        result = export_learning_to_obsidian(args.result_root, args.vault, subdir=args.subdir)
        print(result)
        return
    if args.command == 'export-notion':
        result = export_learning_to_notion(args.result_root, args.database_id, token=args.token or None)
        print(result)
        return


if __name__ == '__main__':
    main()

import argparse
from pathlib import Path

from .pipeline import analyze, analyze_workspace
from .render import render_candidates
from .demo import build_demo


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

    p_render = sub.add_parser('render', help='Render vertical shorts from candidates json')
    p_render.add_argument('--video', type=Path, required=True)
    p_render.add_argument('--candidates', type=Path, required=True)
    p_render.add_argument('--out', type=Path, required=True)
    p_render.add_argument('--top', type=int, default=3)
    p_render.add_argument('--no-burn-subtitles', action='store_true')

    p_demo = sub.add_parser('demo', help='Generate demo transcript/video and run end-to-end')
    p_demo.add_argument('out', type=Path)

    args = parser.parse_args()
    if args.command == 'analyze':
        candidates = analyze(args.transcript, args.highlights, args.out, top_n=args.top_n)
        print(f'wrote {len(candidates)} candidates -> {args.out}')
        return
    if args.command == 'analyze-workspace':
        candidates = analyze_workspace(args.workspace, args.out, top_n=args.top_n)
        print(f'wrote {len(candidates)} candidates -> {args.out}')
        return
    if args.command == 'render':
        rendered = render_candidates(args.video, args.candidates, args.out, top=args.top, burn_subtitles=not args.no_burn_subtitles)
        print(f'rendered {len(rendered)} clips -> {args.out}')
        return
    if args.command == 'demo':
        out = build_demo(args.out)
        print(f'demo ready -> {out}')
        return


if __name__ == '__main__':
    main()

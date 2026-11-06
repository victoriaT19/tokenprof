"""Command-line entry point: `tokenprof proxy ...` and `tokenprof analyze ...`."""

from __future__ import annotations

import argparse
from pathlib import Path

from .analyze import analyze
from .pricing import Pricing
from .proxy import create_app
from .report import render_report
from .trace import TraceWriter, read_traces


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="tokenprof", description="Token profiler for LLM agents.")
    commands = parser.add_subparsers(dest="command", required=True)

    proxy = commands.add_parser("proxy", help="run the logging proxy")
    proxy.add_argument(
        "--upstream",
        required=True,
        help="base URL of the OpenAI-compatible API, e.g. https://api.openai.com/v1",
    )
    proxy.add_argument("--host", default="127.0.0.1")
    proxy.add_argument("--port", type=int, default=8787)
    proxy.add_argument("--out", default="traces.jsonl", help="JSONL file the traces are appended to")
    proxy.add_argument("--pricing", help="JSON price table used to estimate cost per call")
    proxy.add_argument(
        "--no-stream-usage",
        action="store_true",
        help="do not add stream_options.include_usage to streaming requests",
    )
    proxy.add_argument(
        "--restore-thought-signatures",
        action="store_true",
        help="put back Gemini thought signatures that the client dropped from tool calls (changes requests)",
    )

    report = commands.add_parser("analyze", help="analyze a trace file and write an HTML report")
    report.add_argument("traces", help="JSONL file written by the proxy")
    report.add_argument("--out", default="tokenprof-report.html", help="where to write the HTML report")
    report.add_argument(
        "--min-tool-tokens",
        type=int,
        default=1000,
        help="smallest tool output (in tokens) checked for being unused",
    )

    args = parser.parse_args(argv)

    if args.command == "analyze":
        _analyze(args)
    elif args.command == "proxy":
        import uvicorn

        app = create_app(
            args.upstream,
            TraceWriter(args.out),
            Pricing.from_file(args.pricing) if args.pricing else None,
            inject_stream_usage=not args.no_stream_usage,
            restore_thought_signatures=args.restore_thought_signatures,
        )
        uvicorn.run(app, host=args.host, port=args.port)


def _analyze(args: argparse.Namespace) -> None:
    analysis = analyze(read_traces(args.traces), min_tool_tokens=args.min_tool_tokens)
    Path(args.out).write_text(render_report(analysis, source=args.traces), encoding="utf-8")

    totals = analysis.totals()
    prompt = totals["prompt_tokens"]
    wasted = min(prompt, sum(totals["wasted_by_kind"].values()))
    print(f"{totals['calls']} calls in {totals['runs']} run(s), {prompt:,} prompt tokens")
    print(f"estimated waste: {wasted:,} prompt tokens ({wasted / prompt:.0%})" if prompt else "no prompt tokens")
    for kind, tokens in sorted(totals["wasted_by_kind"].items(), key=lambda kv: kv[1], reverse=True):
        print(f"  {kind}: {tokens:,}")
    print(f"report: {args.out}")


if __name__ == "__main__":
    main()

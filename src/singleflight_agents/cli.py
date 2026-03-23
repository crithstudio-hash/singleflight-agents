from __future__ import annotations

import argparse
import asyncio
import sys

from .engine import Singleflight
from .reporting import format_summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="singleflight-agents")
    subparsers = parser.add_subparsers(dest="command", required=True)

    demo = subparsers.add_parser("demo", help="Run the built-in duplicate-work demo.")
    demo.add_argument("--db", default=None, help="SQLite database path.")

    summary = subparsers.add_parser("summary", help="Print receipt summary.")
    summary.add_argument("--db", default=None, help="SQLite database path.")

    verify = subparsers.add_parser("verify", help="Run a basic self-check.")
    verify.add_argument("--db", default=None, help="SQLite database path.")

    openai_demo = subparsers.add_parser("openai-demo", help="Run the optional OpenAI example.")
    openai_demo.add_argument("--db", default=None, help="SQLite database path.")

    langgraph_demo = subparsers.add_parser("langgraph-demo", help="Run the optional LangGraph example.")
    langgraph_demo.add_argument("--db", default=None, help="SQLite database path.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "demo":
        from examples.raw_demo import run_demo

        asyncio.run(run_demo(db_path=args.db))
        return 0

    if args.command == "summary":
        singleflight = Singleflight(db_path=args.db)
        print(format_summary(singleflight.summary()))
        return 0

    if args.command == "verify":
        from examples.raw_demo import verify_runtime

        success = asyncio.run(verify_runtime(db_path=args.db))
        return 0 if success else 1

    if args.command == "openai-demo":
        from examples.openai_demo import main as openai_main

        return openai_main(db_path=args.db)

    if args.command == "langgraph-demo":
        from examples.langgraph_demo import main as langgraph_main

        return langgraph_main(db_path=args.db)

    parser.print_help(sys.stderr)
    return 1

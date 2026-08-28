"""CLI：list-tools | call <tool> '{json}' | serve（stdio MCP）。"""

from __future__ import annotations

import argparse
import json
import sys

from .server import run_stdio
from .tools import TOOL_SPECS, dispatch_tool


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="AutoPilot Platform MCP readonly adapter")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list-tools", help="Print tool JSON schemas")
    call_p = sub.add_parser("call", help="Invoke a tool via REST")
    call_p.add_argument("name")
    call_p.add_argument("arguments_json", nargs="?", default="{}")
    sub.add_parser("serve", help="Run MCP stdio server (requires mcp package)")

    args = p.parse_args(argv)
    if args.cmd == "list-tools":
        print(json.dumps(TOOL_SPECS, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "call":
        try:
            payload = json.loads(args.arguments_json or "{}")
        except json.JSONDecodeError as exc:
            print(f"invalid JSON: {exc}", file=sys.stderr)
            return 2
        print(dispatch_tool(args.name, payload))
        return 0
    if args.cmd == "serve":
        run_stdio()
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

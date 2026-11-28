#!/usr/bin/env python3
"""Usage:
  python3 build.py            Build standalone ./run from src/ modules
  python3 build.py --check    Verify that ./run is up to date with src/ (exit 0 if clean, 1 if stale)
  python3 build.py -h|--help  Print this usage and exit 0
"""
from __future__ import annotations

if __doc__ is None:
    raise SystemExit("missing usage documentation")

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC_DIR = ROOT / "src"
OUT_FILE = ROOT / "run"

MODULE_ORDER = [
    "header.py",
    "config.py",
    "session_meta.py",
    "safety.py",
    "ui.py",
    "ui_info.py",
    "ui_prompt.py",
    "bundle_parse.py",
    "bundle_plan.py",
    "bundle_view.py",
    "runner.py",
    "agent.py",
    "bundle.py",
    "cli.py",
]


def _load_embedded_rule(rel_path: str) -> str:
    raw = (ROOT / rel_path).read_text(encoding="utf-8").replace("\r\n", "\n")
    lines = raw.splitlines()
    while lines and lines[0].startswith("# Description:"):
        lines.pop(0)
    return "\n".join(lines).strip("\n")


def assemble_source() -> str:
    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    bash_rule = _load_embedded_rule("agents/run.md")
    api_rule = _load_embedded_rule("agents/run-api.md")
    chunks: list[str] = []
    for item in MODULE_ORDER:
        mod_path = SRC_DIR / item
        txt = mod_path.read_text(encoding="utf-8").rstrip()
        if item == "header.py":
            txt = txt.replace('VERSION = "__VERSION__"', f'VERSION = "{ver}"')
            txt = txt.replace('EMBEDDED_RULE_BASH = "__EMBEDDED_RULE_BASH__"', f"EMBEDDED_RULE_BASH = {bash_rule!r}")
            txt = txt.replace('EMBEDDED_RULE_API = "__EMBEDDED_RULE_API__"', f"EMBEDDED_RULE_API = {api_rule!r}")
        chunks.append(txt)
    source = "\n\n\n".join(chunks) + "\n"
    ast.parse(source)
    return source


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "-h" in args or "--help" in args:
        sys.stdout.write(__doc__)
        return 0
    expected = assemble_source()
    if "--check" in args:
        if not OUT_FILE.is_file() or OUT_FILE.read_text(encoding="utf-8") != expected:
            sys.stderr.write("build.py: run is out of sync with src/ (run 'python3 build.py')\n")
            return 1
        return 0
    if args:
        sys.stderr.write(__doc__)
        return 2
    OUT_FILE.write_text(expected, encoding="utf-8")
    OUT_FILE.chmod(0o755)
    sys.stdout.write(f"build.py: built {OUT_FILE} ({len(expected.splitlines())} lines)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

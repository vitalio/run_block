#!/usr/bin/env python3
"""Usage:
  python3 build.py            Build standalone ./run_block from src/ modules
  python3 build.py --check    Verify that ./run_block is up to date with src/ (exit 0 if clean, 1 if stale)
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
OUT_FILE = ROOT / "run_block"

MODULE_ORDER = [
    "header.py",
    "config.py",
    "safety.py",
    "ui.py",
    "runner.py",
    "bundle.py",
    "cli.py",
]


def assemble_source() -> str:
    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    chunks: list[str] = []
    for item in MODULE_ORDER:
        mod_path = SRC_DIR / item
        txt = mod_path.read_text(encoding="utf-8").rstrip()
        if item == "header.py":
            txt = txt.replace('VERSION = "__VERSION__"', f'VERSION = "{ver}"')
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
            sys.stderr.write("build.py: run_block is out of sync with src/ (run 'python3 build.py')\n")
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

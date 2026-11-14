#!/usr/bin/env python3
# run_block-repo: vitalio/run_block
"""Usage:
  agents_bundle | {prog}             Start a new session from stdin context bundle into {base_dir}/<session>/0.txt
  {prog} [-y] <session>/<step>       Run block from stdin (-y/--yes for non-interactive headless mode)
  {prog} --plan                      Analyze script from stdin and print JSON execution & safety plan
  {prog} --fix [-y] <session>/<ref>  Patch <ref> script via Python on stdin and run as <ref>_N
  {prog} --retry [-y] [session/step] Re-run the last (or specified) block
  {prog} --list | -l [session]       List sessions or blocks in a session
  {prog} --show [session/step]       Show script and output of a block (or <session>/0 bundle)
  {prog} --clean [--keep N | --all]  Prune old session directories in {base_dir} (default: --keep 5)
  {prog} --start [opts]              Start session with explicit options (--session NAME, --force)
  {prog} --agents                    Print Markdown instructions for AI agents
  {prog} --update [--force]          Self-update {prog} from GitHub (vitalio/run_block)
  {prog} --check-update              Check if a newer version is available
  {prog} -V | --version              Print version and exit 0
  {prog} -h | --help                 Print this usage and exit 0
"""
from __future__ import annotations

if __doc__ is None:
    raise SystemExit("missing usage documentation")

import ast
import difflib
import json
import math
import os
import re
import select
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unicodedata
import urllib.request
from datetime import datetime
from pathlib import Path

try:
    import pty
    import termios
    import tty
    HAS_PTY = True
except ImportError:
    pty = None  # type: ignore[assignment]
    termios = None  # type: ignore[assignment]
    tty = None  # type: ignore[assignment]
    HAS_PTY = False

VERSION = "0.16.2"
REPO_MARKER = "run_block-repo: vitalio/run_block"
DEFAULT_UPDATE_URL = "https://raw.githubusercontent.com/vitalio/run_block/main/run_block"

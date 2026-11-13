#!/usr/bin/env python3
# run_block-repo: vitalio/run_block
"""Usage:
  {prog} [<session>/<step>]          Run Bash block from stdin (omit ref on first block to auto-init <session>/1)
  {prog} --fix <session>/<target>    Patch <target>.sh via Python on stdin and run as <target>_N
  {prog} --retry [session/step]      Re-run the last (or specified) block
  {prog} --list | -l [session]       List sessions or blocks in a session
  {prog} --show [session/step]       Show script and output of a block (or <session>/0 bundle)
  {prog} --clean [--keep N | --all]  Prune old session directories in {base_dir} (default: --keep 5)
  {prog} --tree [DIR] [opts]         Print token-budgeted repository file tree (--max-lines N, --max-tokens N)
  {prog} --start [opts] [FILE ...]   Build session bundle ({base_dir}/<session>/0.txt) from .run_block.start
                                        Opts: --session NAME, -p/--prompt TEXT, --force
  {prog} --init-start [--force]      Create a starter .run_block.start in the current directory
  {prog} --agents [ITEM ...|--list]  Print AI agent rules/presets (default, blocks, workflow, python-tool, -rule, k=v)
  {prog} --config                    Show active configuration ({config_path})
  {prog} --init-config [--force]     Create default config file at {config_path}
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

VERSION = "0.12.0"
REPO_MARKER = "run_block-repo: vitalio/run_block"
DEFAULT_UPDATE_URL = "https://raw.githubusercontent.com/vitalio/run_block/main/run_block"
START_FILE_NAME = ".run_block.start"

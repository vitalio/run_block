#!/usr/bin/env python3
# run-block-repo: vitalio/run-block
"""Safe, sequential terminal block execution protocol for AI coding agents."""
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
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unicodedata
from datetime import datetime, timezone
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

VERSION = "__VERSION__"
REPO_MARKER = "run-block-repo: vitalio/run-block"
LEGACY_REPO_MARKER = "run_block-repo: vitalio/run_block"
REPO_MARKERS = (REPO_MARKER, LEGACY_REPO_MARKER)
DEFAULT_UPDATE_URL = "https://raw.githubusercontent.com/vitalio/run-block/main/run"
EMBEDDED_RULE_BASH = "__EMBEDDED_RULE_BASH__"
EMBEDDED_RULE_API = "__EMBEDDED_RULE_API__"


HELP_USAGE = (
    "{prog} [options] [<session>/<step>]",
    "<command> | {prog} [options]",
)

HELP_SESSION_COMMANDS = (
    ("{prog}", "Start a rule-only session on TTY stdin (or read a bundle from piped stdin)"),
    ("<command> | {prog}", "Start a new session from a stdin context bundle into {base_dir}/<session>/0"),
    ("--start [opts]", "Start a session from stdin or rule-only on TTY (--session NAME, --force)"),
    ("[-y] <session>/<step>", "Run the block from stdin (-y/--yes: auto-confirm START STEP and reopen a completed session)"),
    ("-r | --run [-c] [-y] [sess]", "Run full model reply from clipboard (-c), editor (TTY), or stdin with step inference"),
    ("--fix [-y] <session>/<ref>", "Patch <ref> script via Python on stdin and run as <ref>_N"),
    ("--retry [-y] [session/step]", "Re-run the last block of a session or <session>/<step>"),
    ("--done [session] [-m NOTE]", "Mark session completed and print END SESSION summary (later blocks ask to reopen)"),
)

HELP_INSPECT_COMMANDS = (
    ("--list | -l [session]", "List sessions/blocks: last step, next free step ([DONE] = completed)"),
    ("--list --filter TEXT", "List only sessions whose name or headers contain TEXT"),
    ("--show [session[/step]]", "Show session info (<session>), <session>/0 bundle, or block script, output, and backups"),
    ("--show <session> --part N", "Print only part N of <session>/0 (1-based part index, see --bundle-plan --json)"),
    ("--show <ref> --script|--out", "Print only a block's script or only its output"),
    ("--bundle-plan [sess]", "Print the Parts table and warnings of a bundle from stdin or session (--json)"),
    ("--plan", "Analyze the script from stdin and print the JSON execution and safety plan"),
)

HELP_CONFIG_COMMANDS = (
    ("--config [KEY[=VALUE] | --edit | --path]", "Show settings with sources, profiles, and roles; get/set a key in config.json (KEY= unsets), open in editor (--edit), or print path (--path)"),
    ("--sandbox [MODE] [session]", "Show or set session sandbox mode (off, strict, nonet)"),
    ("--clean [opts] [session...]", "Prune sessions in {base_dir} (--keep N, --older-than DAYS, --max-size MB, --all)"),
    ("--update [--check | --force]", "Self-update {prog} from GitHub (vitalio/run-block) or check for a newer version (--check)"),
    ("--uninstall [--purge]", "Remove installed {prog} binary (--purge also removes {base_dir})"),
)

HELP_COMMAND_SECTIONS = (
    ("Session & Execution Commands:", HELP_SESSION_COMMANDS),
    ("Inspection & History Commands:", HELP_INSPECT_COMMANDS),
    ("Configuration & Maintenance Commands:", HELP_CONFIG_COMMANDS),
)

HELP_COMMANDS = (*HELP_SESSION_COMMANDS, *HELP_INSPECT_COMMANDS, *HELP_CONFIG_COMMANDS)

HELP_OPTIONS = (
    ("-r, --run [session]", "Full-reply mode: extract block & reasoning from clipboard (-c), editor (TTY), or piped stdin"),
    ("-c, --clipboard", "Read full model reply directly from system clipboard (use with -r/--run, e.g. {prog} -rc)"),
    ("-y, --yes", "Auto-confirm START STEP and reopen a completed session (keeps TUI cards and clipboard prompts)"),
    ("--headless", "Non-interactive headless mode without TUI boxes or prompts (same as RUN_BLOCK_HEADLESS=1)"),
    ("-p, --prompt TEXT", "Embed repeatable prompt text into the started session bundle (===== Prompt =====)"),
    ("-P, --profile NAME", "Model profile for the started session (overrides role routing and default_profile; saved in meta.json)"),
    ("--sandbox [MODE]", "Set the sandbox mode for the run or started session (off, strict, nonet); bare flag means strict"),
    ("-V, --version", "Print version and exit 0"),
    ("-h, --help", "Print this usage and exit 0"),
)

HELP_ENV = (
    ("RUN_BLOCK_CONFIG=PATH", "User config file (default: XDG_CONFIG_HOME/run-block/config.json, fallback models.json)"),
    ("RUN_BLOCK_MODEL[_<ROLE>]=NAME", "Model profile (or <provider>:<model>) for all sessions or one role"),
    ("RUN_BLOCK_CACHE=auto|system|off", "Prompt cache breakpoint mode for API sessions"),
    ("RUN_BLOCK_CWD=auto|cwd|PATH", "Working directory (auto prefers piped/session Workdir, project root, or $PWD)"),
    ("RUN_BLOCK_PAGER=cat|inherit", "Non-interactive pager for child steps (PAGER, GIT_PAGER, GH_PAGER, MANPAGER, ...; inherit/off keeps parent env)"),
    ("VISUAL / EDITOR", "Editor/viewer for e(dit), s(cript), o(utput), and v(iew) inside i(nfo) (keeps *.orig backups)"),
)

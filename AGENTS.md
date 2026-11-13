# `run_block` — Engineering Rules

- **Zero external dependencies:** Python 3.9+ standard library only (`from __future__ import annotations` at top of Python files for macOS system Python 3.9 compatibility).
- **Pre-commit checks:**
  - `bash -n install.sh && shellcheck -S warning install.sh`
  - `python3 -W error -c 'from pathlib import Path; import ast; ast.parse(Path("run_block").read_text())'`
  - `python3 tests/test_run_block.py -v`
- **Release rule on CLI/installer changes:** Whenever `run_block`, `install.sh`, or `install.ps1` is modified:
  1. Bump semantic version in both `VERSION` and `VERSION = "..."` inside `run_block`.
  2. Reinstall locally: `sh install.sh --yes >/dev/null`
  3. Commit, push to `origin main`, and push an annotated release tag (`git tag -a vX.Y.Z -m "Release vX.Y.Z" && git push origin vX.Y.Z`).

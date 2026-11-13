# `run_block` — Project-Specific Agent Rules

Universal workflow, SemVer, and Python CLI rules are loaded via `$ run_block --rules workflow semver python-cli`.

## Pre-commit checks

- `bash -n install.sh && shellcheck -S warning install.sh`
- `python3 -W error -c 'from pathlib import Path; import ast; ast.parse(Path("run_block").read_text())'`
- `python3 tests/test_run_block.py -v`

## Release trigger & local reinstall

- Whenever `run_block`, `install.sh`, or `install.ps1` is modified, bump `VERSION` and `VERSION = "..."` in `run_block`, reinstall locally via `sh install.sh --yes >/dev/null`, commit, push to `origin main`, and push annotated tag `vX.Y.Z`.

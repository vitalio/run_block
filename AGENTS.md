# run_block: rules and workflow for an AI agent

Operational contract for an AI agent working on `run_block`.
[README.md](README.md) documents features, installation, and CLI reference;
[TODO.md](TODO.md) holds the current state (`Resume`) and active roadmap tasks.
Run `run_block --start` (configured via [.run_block.start](.run_block.start)) to generate
a complete session context bundle (`/tmp/run_block/<session>/0.txt`) that includes
this file, [TODO.md](TODO.md), `run_block --agents`, and current Git state.

## Project architecture and files

- `run_block` — standalone executable Python 3 CLI (zero external dependencies; supports Python 3.9+ on Linux, macOS, and Windows).
- `.run_block.start` — declarative specification of files and `$ <cmd>` commands bundled by `run_block --start` into `<session>/0.txt`.
- `VERSION` — single-line semantic version string (`0.6.1`), must match `VERSION` inside `run_block`.
- `install.sh` — POSIX shell installer for Linux and macOS (checks `PATH` conflicts, installs to `~/.local/bin`, runs `--agents`).
- `install.ps1` — PowerShell 7+ installer for Windows.
- `tests/test_run_block.py` — unit test suite (`unittest`, no network required).
- `.github/workflows/ci.yml` — GitHub Actions CI (`ubuntu-latest`, `macos-latest`) and automatic GitHub Release on `v*` tags.

## Engineering rules and local checks

- **Zero external dependencies:** Use only the Python 3 standard library. Keep `from __future__ import annotations` at the top of Python files so Apple's system Python 3.9 on macOS works out of the box.
- **Syntax and lint checks before committing:**
  ```bash
  bash -n install.sh
  shellcheck -S warning install.sh
  python3 -W error -c 'import ast; ast.parse(open("run_block").read())'
  python3 tests/test_run_block.py -v
  ```
- **Keep local binary in sync:** Whenever `run_block` or `VERSION` changes, run:
  ```bash
  sh install.sh --yes >/dev/null
  ```
- **Versioning and release tags on every CLI/installer change:** Whenever `run_block`, `install.sh`, or `install.ps1` is modified, bump the version in both `VERSION` and `VERSION = "..."` inside `run_block` (and `AGENTS.md`), reinstall locally (`sh install.sh --yes >/dev/null`), commit, push `origin main`, and push an annotated release tag (`git tag -a vX.Y.Z -m "Release vX.Y.Z" && git push origin vX.Y.Z`) so `--update` / `--check-update` and GitHub Releases always stay up to date.
- **Git identity:** Commits in this repository use `Vitaly <2vitalio@gmail.com>` and push to `origin main` (`git@github.com-2vitalio:vitalio/run_block.git`).

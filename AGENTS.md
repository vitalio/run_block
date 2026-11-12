# run_block: rules and workflow for an AI agent

Operational contract for an AI agent working on `run_block`.
[README.md](README.md) documents features, installation, and CLI reference;
[TODO.md](TODO.md) holds the current state (`Resume`) and active roadmap tasks.

<!-- run_block:start v0.5.0 -->
## Terminal blocks (`run_block` v0.5.0)

You have no direct shell access. Run commands by giving the user a
`run_block` terminal block.

**CRITICAL — ONE BLOCK PER MESSAGE:**
- Give **at most ONE** executable `run_block` block per message.
- Place it at the **very end** of your reply with **zero trailing text** after the closing fence.
- Never assume a block ran until the user pastes its output.

### 1. Normal block (`<session>/<step>`)

Use the session ID (`s1`, `s2`, ...) and the next sequential step number (`1`, `2`, `3`, ...):

```bash
run_block s1/1 <<'RUN_BLOCK'
git status -sb
RUN_BLOCK
```

- Runs in `bash` from the repository root (or current working directory).
- Every launched step consumes its number, even if it fails. Never reuse a step number or skip ahead.
- **Markdown fence safety:** Keep a blank line before the opening fence. Never put literal triple backticks or the heredoc delimiter (`RUN_BLOCK` / `RUN_FIX`) inside a block body (in Python, build backticks as `F3 = chr(96) * 3`).

### 2. Fixing a failed block (`--fix <session>/<target>`)

When a long block fails on a small mistake and re-running is safe, patch the previous script (`text` in Python) instead of regenerating the whole block:

```bash
run_block --fix s1/2 <<'RUN_FIX'
old = 'wrong_command'
new = 'right_command'
assert text.count(old) == 1
text = text.replace(old, new, 1)
RUN_FIX
```

- Modifies `text` from `<target>` and runs it as `<target>_1` (fixing `2` runs `2_1`; fixing `2_1` runs `2_2`).
- If the failed run already partially changed state and is not idempotent, use the next normal step (`s1/3`) instead of `--fix`.
<!-- run_block:end -->

## Project architecture and files

- `run_block` — standalone executable Python 3 CLI (zero external dependencies; supports Python 3.9+ on Linux, macOS, and Windows).
- `VERSION` — single-line semantic version string (`0.5.0`), must match `VERSION` inside `run_block`.
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
  python3 tests/test_run_block.py -v
  ```
- **Keep local binary and `AGENTS.md` in sync:** Whenever `run_block` or `VERSION` changes, run:
  ```bash
  ./run_block --agents-install AGENTS.md
  sh install.sh --yes >/dev/null
  ```
- **Git identity and releases:** Commits in this repository use `Vitaly <2vitalio@gmail.com>` and push to `origin main` (`git@github.com-2vitalio:vitalio/run_block.git`). Tag releases as `vX.Y.Z` so GitHub Actions publishes the release.

## Task structure (`TODO.md`)

Every task heading in [TODO.md](TODO.md) uses:
`### <emoji> [<STATUS>] <ID>: <title>` with one of:
- `⚪ [NEW]` — planned, not started
- `🔵 [WIP]` — in progress
- `⏸️ [HOLD]` — waiting on an external dependency
- `❓ [QUESTION]` — needs human decision
- `✅ [DONE]` — completed
- `❌ [CANCELED]` — dropped

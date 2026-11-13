# `run_block` — AI Agent Rules

## 1. Workflow: Start → Investigate → Plan → Edit → Test → Commit → End

- **Start:** Uncommitted changes or in-flight work take precedence over new tasks — ask what to do first. Format dates in chat as `DD/MM/YYYY`, and in files/commits/logs as ISO `YYYY-MM-DD`.
- **Investigate:** Read code rather than guessing; say "not known" rather than filling gaps.
- **Plan:** Before non-trivial edits, state a high-level plan (target outcome, rules, and behavior — not a line-by-line diff dump) and write code once agreed.
- **Edit:** Write file edits in Python asserting each anchor occurs once (`assert text.count(old) == 1`) before writing. Avoid multiline triple-quoted strings when `"
".join([...])` is cleaner. Update `README.md` and `-h`/`--help` usage whenever CLI behavior or config options change.
- **Test & self-review diff:** Run pre-commit checks and inspect `git diff HEAD`:
  - `bash -n install.sh && shellcheck -S warning install.sh`
  - `python3 -W error -c 'from pathlib import Path; import ast; ast.parse(Path("run_block").read_text())'`
  - `python3 tests/test_run_block.py -v`
  Audit the diff for dead code, regressions, and docs sync before committing (trivial 1–2 line edits may edit, test, and commit in one block).
- **Commit & release:** Never run `git push --force`, `git reset --hard`, or delete branches/tags without explicit user approval. Whenever `run_block`, `install.sh`, or `install.ps1` is modified:
  1. Bump `VERSION` and `VERSION = "..."` inside `run_block` (`PATCH` `0.Y.Z+1` for bugfixes, UI/box tweaks, and `--agents`/`--help` updates; `MINOR` `0.Y+1.0` for new CLI commands/flags or config options; `MAJOR` `X+1.0.0` only when explicitly requested).
  2. Reinstall locally: `sh install.sh --yes >/dev/null`
  3. Commit, push to `origin main`, and push an annotated release tag (`git tag -a vX.Y.Z -m "Release vX.Y.Z" && git push origin vX.Y.Z`).
- **End:** On "end session" (or task completion), give a concise summary of completed work (with commit SHAs), report any uncommitted/unpushed changes, and update `Resume` in `TODO.md`.

## 2. Engineering invariants

- **Zero external dependencies:** Use only the Python 3 standard library (`from __future__ import annotations` at top of Python files for macOS system Python 3.9 compatibility).
- **Single responsibility & clean CLI:** Every flag/command must be documented in `-h`/`--help` (which exits `0` doing nothing) and covered by unit tests in `tests/test_run_block.py`.

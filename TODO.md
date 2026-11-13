# run_block — active tasks and operational state

`README.md` documents installation and CLI usage; `AGENTS.md`
defines the rules and workflow for an AI agent working on this repository.

Task heading format: `### <emoji> [<STATUS>] <ID>: <title>`
(`⚪ [NEW]`, `🔵 [WIP]`, `⏸️ [HOLD]`, `❓ [QUESTION]`, `✅ [DONE]`, `❌ [CANCELED]`).

## Resume

Written 2026-11-13. Released `run_block` `v0.11.0` (`83863e7`):
- Completed `F6`: split monolithic `run_block` into modular `src/` (`src/templates/*.md`, `src/rules/*.md` with 13 atomic rules, `src/presets.txt` with rule groups `workflow`, `default`, `python-tool`, and 9 `src/*.py` modules) compiled into standalone `./run_block` via `build.py` (verified by `build.py --check` in unit tests).
- Added support for rule presets, `-<rule>` exclusions, `{var:default}` template variables (`key=val`), and automatic `git`/`cvs` VCS rule detection in `run_block --agents-rules`.
- Earlier in session: completed `F1`–`F5` (`v0.8.0`–`v0.10.0`). All tasks in `TODO.md` and `TODO_PLAN.md` are complete.

## Tasks

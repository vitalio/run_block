# run_block — active tasks and operational state

`README.md` documents installation and CLI usage; `AGENTS.md`
defines the rules and workflow for an AI agent working on this repository.

Task heading format: `### <emoji> [<STATUS>] <ID>: <title>`
(`⚪ [NEW]`, `🔵 [WIP]`, `⏸️ [HOLD]`, `❓ [QUESTION]`, `✅ [DONE]`, `❌ [CANCELED]`).

## Resume

Written 2026-11-13. Released `run_block` `v0.9.0` (`f618c65`):
- Completed `F5`: added `run_block --rules [TOPIC ... | all | --list]` with built-in reusable engineering rule modules (`workflow`, `semver`, `python-cli`) and custom user rule files in `~/.config/run_block/rules/*.md`, plus in-process execution from `.run_block.start`.
- Slimmed `AGENTS.md` in both `run_block` and `~/todo_md` to project-specific rules only, loading universal rules via `$ run_block --rules workflow semver python-cli` in `.run_block.start`.
- Earlier in session: released `v0.8.0` (`15f24a8`) completing `F1` (PowerShell mode), `F2` (custom safety rules), `F3` (`--clean`), and `F4` (`--tree`).

## Tasks

# run_block — active tasks and operational state

`README.md` documents installation and CLI usage; `AGENTS.md`
defines the rules and workflow for an AI agent working on this repository.

Task heading format: `### <emoji> [<STATUS>] <ID>: <title>`
(`⚪ [NEW]`, `🔵 [WIP]`, `⏸️ [HOLD]`, `❓ [QUESTION]`, `✅ [DONE]`, `❌ [CANCELED]`).

## Resume

Written 2026-11-13. Released `run_block` `v0.9.1` (`d489bd8`):
- Included `$ run_block --rules` (`workflow` by default) in `run_block --start` built-in defaults when `.run_block.start` is absent, and stopped scanning child subdirectories for `.run_block.start`.
- Earlier in session: released `v0.9.0` (`f618c65`, task `F5`: `run_block --rules`) and `v0.8.0` (`15f24a8`, tasks `F1`–`F4`: PowerShell mode, custom safety rules, `--clean`, and `--tree`).

## Tasks

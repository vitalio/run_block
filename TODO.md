# run_block — active tasks and operational state

`README.md` documents installation and CLI usage; `AGENTS.md`
defines the rules and workflow for an AI agent working on this repository.

Task heading format: `### <emoji> [<STATUS>] <ID>: <title>`
(`⚪ [NEW]`, `🔵 [WIP]`, `⏸️ [HOLD]`, `❓ [QUESTION]`, `✅ [DONE]`, `❌ [CANCELED]`).

## Resume

Written 2026-11-14. Released `run_block` `v0.14.0` (`412de9c`):
- Removed file-based configuration (`~/.config/run_block/config`, `--config`, `--init-config`) in favor of zero-config defaults and standard environment variables (`VISUAL`/`EDITOR`, `RUN_BLOCK_*`).
- Added `run_block --plan` to analyze scripts from `stdin` and emit structured JSON execution and safety plans to `stdout`.
- Added `-y`/`--yes` (`RUN_BLOCK_HEADLESS=1`) non-interactive headless mode for raw `stdout` protocol execution without `/dev/tty` boxes.
- Added `RUN_BLOCK_APPROVE_CMD` pre-execution validator hook receiving `--plan` JSON on `stdin` (`0`=auto-approve, `2`=prompt user with analyzer note in `BLOCK PLAN`, other=reject).
- Updated `run_block --agents` fence safety rules to prefer targeted `text.replace` patches over whole-file Markdown rewrites.

## Tasks

# run_block — active tasks and operational state

[README.md](README.md) documents installation and CLI usage; [AGENTS.md](AGENTS.md)
defines the rules and workflow for an AI agent working on this repository.

Task heading format: `### <emoji> [<STATUS>] <ID>: <title>`
(`⚪ [NEW]`, `🔵 [WIP]`, `⏸️ [HOLD]`, `❓ [QUESTION]`, `✅ [DONE]`, `❌ [CANCELED]`).

## Resume

Written 2026-11-13. Released `run_block` `v0.6.2`:
- Strengthened `run_block --agents` with explicit `CRITICAL — STRICT BLOCK GENERATION & LAYOUT RULES` (strict single-block-per-message rule, end-of-message placement with zero trailing text, column-0 fence/heredoc layout, and no inner triple backticks).
- Placed `$ run_block --agents` first in `.run_block.start`, `default_start_template()`, and `README.md`.
- Made `<session>/0.txt` bundle header minimal (`Session`, `Next block`, `Workdir`) while keeping the detailed section/token manifest in console output during `run_block --start`.
- Unified `Workdir` resolution so that when `.run_block.start` is located in a subdirectory, its directory is used as `Workdir` both for `--start` and for subsequent block executions in the session.
- Next in queue: `F1` (PowerShell execution mode on Windows), `F2` (custom safety rules in config), `F3` (`--clean` session pruning).

To start a new chat session: run `run_block --start`.

## Tasks

### ⚪ [NEW] F1: Native PowerShell (`pwsh`) block execution mode on Windows

Allow `shell = pwsh` in `~/.config/run_block/config` so Windows users in PowerShell 7
can execute native PowerShell blocks in addition to Bash blocks.

### ⚪ [NEW] F2: Custom user-defined safety rules in config

Allow adding custom regex patterns or overriding risk categories in
`~/.config/run_block/config`.

### ⚪ [NEW] F3: Session cleanup command (`--clean`)

Add `run_block --clean [--keep N | --all]` to prune old session directories in
`/tmp/run_block`.

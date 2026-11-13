# run_block — active tasks and operational state

[README.md](README.md) documents installation and CLI usage; [AGENTS.md](AGENTS.md)
defines the rules and workflow for an AI agent working on this repository.

Task heading format: `### <emoji> [<STATUS>] <ID>: <title>`
(`⚪ [NEW]`, `🔵 [WIP]`, `⏸️ [HOLD]`, `❓ [QUESTION]`, `✅ [DONE]`, `❌ [CANCELED]`).

## Resume

Written 2026-11-13. Released `run_block` `v0.6.3`:
- Redesigned `run_block --agents` so the standard `<cmd> s1/1 <<'RUN_BLOCK'` template appears immediately at the top, eliminated nested 4/5-backtick inline escapes from rules, added explicit guidance on batching multiple commands inside a single block, and prohibited literal inner `RUN_BLOCK`/`RUN_FIX` delimiters in addition to triple backticks.
- Added interactive confirmation (`prompt_yes_no_box`) when a previous step was skipped (`[!] MISSING PREVIOUS STEP`), when a step already exists (`[!] STEP ALREADY EXISTS`), and when a session already exists (`[!] SESSION ALREADY EXISTS`).
- Framed `run_block --start` console bundle summary in a box (`format_info_box`) matching `BLOCK PLAN` and `END`.
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

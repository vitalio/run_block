# run_block — active tasks and operational state

`README.md` documents installation and CLI usage; `AGENTS.md`
defines the rules and workflow for an AI agent working on this repository.

Task heading format: `### <emoji> [<STATUS>] <ID>: <title>`
(`⚪ [NEW]`, `🔵 [WIP]`, `⏸️ [HOLD]`, `❓ [QUESTION]`, `✅ [DONE]`, `❌ [CANCELED]`).

## Resume

Written 2026-11-13. Released `run_block` `v0.6.6`:
- Tightened terminal box width calculation (`format_info_box`, `format_prompt_box`, `format_safety_box`, `format_clipboard_box`) by removing the 52-char minimum width and extra right padding so every box fits its content with exactly 1 space of left/right padding.
- Framed all block lifecycle messages (`START`, `SYNTAX ERROR`, `NOT RUN`, `END`) in terminal boxes (`v0.6.5`), removed `TODO.md` references from `run_block` (`v0.6.4`), and updated `AGENTS.md` with explicit `PATCH`/`MINOR`/`MAJOR` versioning rules.
- Next in queue: `F1` (PowerShell execution mode on Windows), `F2` (custom safety rules in config), `F3` (`--clean` session pruning); deferred: `F4` (`--tree` smart repo map).

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

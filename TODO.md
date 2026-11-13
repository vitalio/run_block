# run_block — active tasks and operational state

`README.md` documents installation and CLI usage; `AGENTS.md`
defines the rules and workflow for an AI agent working on this repository.

Task heading format: `### <emoji> [<STATUS>] <ID>: <title>`
(`⚪ [NEW]`, `🔵 [WIP]`, `⏸️ [HOLD]`, `❓ [QUESTION]`, `✅ [DONE]`, `❌ [CANCELED]`).

## Resume

Written 2026-11-13. Released `run_block` `v0.6.3` (`931ad4b`) and decoupled documentation from `todo_md`:
- Redesigned `run_block --agents` with immediate `<cmd> s1/1 <<'RUN_BLOCK'` template, command batching guidance, and strict fence/heredoc protection.
- Added interactive confirmation (`prompt_yes_no_box`) for skipped previous steps (`[!] MISSING PREVIOUS STEP`), existing steps, and existing sessions, plus `format_info_box` for `run_block --start`.
- Slimmed `AGENTS.md` to non-computable engineering & release rules and removed cross-references to `todo_md` from `README.md`.
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

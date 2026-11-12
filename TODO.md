# run_block — active tasks and operational state

[README.md](README.md) documents installation and CLI usage; [AGENTS.md](AGENTS.md)
defines the rules and workflow for an AI agent working on this repository.

Task heading format: `### <emoji> [<STATUS>] <ID>: <title>`
(`⚪ [NEW]`, `🔵 [WIP]`, `⏸️ [HOLD]`, `❓ [QUESTION]`, `✅ [DONE]`, `❌ [CANCELED]`).

## Resume

Written 2026-11-12. Released `run_block` `v0.6.0`:
- Automatic first-block session initialization (`run_block <<'RUN_BLOCK'` without `<session>/<step>` initializes a new session or reuses a `--start` session and runs step `1`, reserving step `0` for the start bundle).
- Declarative session context bundler (`run_block --start [options] [FILE ...]` and `run_block --init-start`) powered by [.run_block.start](.run_block.start) (combines UTF-8 project files and `$ <command>` outputs into `/tmp/run_block/<session>/0.txt` with token counts and clipboard prompt).
- Updated `run_block --agents` instructions and removed `--agents-install` so `AGENTS.md` stays clean and project-specific.
- Pre-execution `BLOCK PLAN` + 6-category `Safety warnings` scanner with `tcflush` input protection.
- Single-keystroke `Enter` (copy) / `Esc` (skip) clipboard prompt with byte size and Claude/GPT/Gemini token counts.
- Session and block navigation (`--list` / `-l`, `--show`, `--retry` / `--rerun`, `--start`).
- Configuration file support (`~/.config/run_block/config`, `--config`, `--init-config`) and self-update (`--update`, `--check-update`).

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

# run_block — active tasks and operational state

`README.md` documents installation and CLI usage; `AGENTS.md`
defines the rules and workflow for an AI agent working on this repository.

Task heading format: `### <emoji> [<STATUS>] <ID>: <title>`
(`⚪ [NEW]`, `🔵 [WIP]`, `⏸️ [HOLD]`, `❓ [QUESTION]`, `✅ [DONE]`, `❌ [CANCELED]`).

## Resume

Written 2026-11-14. Released `run_block` `v0.15.0` (`1ce929c`):
- Made `agents_bundle | run_block` (no arguments with piped `stdin`) initialize a new session bundle (`<session>/0.txt`), removing implicit sessionless block execution.
- Refined TUI box headers to `<label> · <TITLE>`, removed the redundant `START` box in favor of `✓ Running <script> ...` in `BLOCK PLAN`, added blank line spacing between directory groups in `Operations:`, and unified the `[python]` operation tag.
- Replaced duplicate release instructions in `AGENTS.md` with module boundary documentation.

## Tasks

# run_block — active tasks and operational state

`README.md` documents installation and CLI usage; `AGENTS.md`
defines the rules and workflow for an AI agent working on this repository.

Task heading format: `### <emoji> [<STATUS>] <ID>: <title>`
(`⚪ [NEW]`, `🔵 [WIP]`, `⏸️ [HOLD]`, `❓ [QUESTION]`, `✅ [DONE]`, `❌ [CANCELED]`).

## Resume

Written 2026-11-13. Released `run_block` `v0.13.0`, `agents_bundle` `v0.2.0` (`e9b37c0`), and `agents_rules` `v0.2.0` (`5ed3e03`):
- Unified `.agents_bundle` as a root preset supporting `preset <pkg>:<name>`, `rule <pkg>:<name>`, and `$ <cmd>` (e.g. `$ cat AGENTS.md`) executed by `agents_bundle` and piped into `run_block --start`.
- Deferred in `TODO_PLAN.md`: `F7` (plugin system + LLM block analyzer + headless mode) and `F9` (Unix philosophy audit of `run_block` and `todo_md`).

## Tasks

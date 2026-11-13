# run_block — active tasks and operational state

`README.md` documents installation and CLI usage; `AGENTS.md`
defines the rules and workflow for an AI agent working on this repository.

Task heading format: `### <emoji> [<STATUS>] <ID>: <title>`
(`⚪ [NEW]`, `🔵 [WIP]`, `⏸️ [HOLD]`, `❓ [QUESTION]`, `✅ [DONE]`, `❌ [CANCELED]`).

## Resume

Written 2026-11-13. Released `run_block` `v0.13.0` (`99bc5e1`), `agents_rules` `v0.1.0`, and `agents_bundle` `v0.1.0`:
- Completed `F8`: created and published standalone GitHub repositories `vitalio/agents_rules` (`v0.1.0`, namespaced rule & preset package manager/renderer) and `vitalio/agents_bundle` (`v0.1.0`, pure Unix context bundler and `--tree`).
- Slimmed `run_block` (`v0.13.0`) to a pure block execution protocol where `run_block --start` reads the context bundle from `stdin` (`agents_bundle | run_block --start`) and `run_block --agents` prints only the terminal block protocol.
- Deferred in `TODO_PLAN.md`: `F7` (plugin system + LLM block analyzer + headless mode) and `F9` (Unix philosophy audit of `run_block` and `todo_md`).

## Tasks

# run_block — active tasks and operational state

`README.md` documents installation and CLI usage; `AGENTS.md`
defines the rules and workflow for an AI agent working on this repository.

Task heading format: `### <emoji> [<STATUS>] <ID>: <title>`
(`⚪ [NEW]`, `🔵 [WIP]`, `⏸️ [HOLD]`, `❓ [QUESTION]`, `✅ [DONE]`, `❌ [CANCELED]`).

## Resume

Written 2026-11-13. Released `run_block` `v0.13.0`, `agents_bundle` `v0.2.1` (`86ab670`), and `agents_rules` `v0.3.0` (`aabeeb9`):
- Separated pure OS-agnostic `core/` rules from `os/` (`linux`, `macos`, `windows`, `os/auto`), `stack/` (`cli`, `python-cli`), and `collab/external` in `vitalio/agents_rules`.
- Merged consecutive `preset`/`rule` directives into a single `Rules` section in `agents_bundle` with `-v`/`--verbose` provenance tracing.
- Deferred in `TODO_PLAN.md`: `F7` (plugin system + LLM block analyzer + headless mode) and `F9` (Unix philosophy audit of `run_block` and `todo_md`).

## Tasks

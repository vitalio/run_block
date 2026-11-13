# run_block — active tasks and operational state

`README.md` documents installation and CLI usage; `AGENTS.md`
defines the rules and workflow for an AI agent working on this repository.

Task heading format: `### <emoji> [<STATUS>] <ID>: <title>`
(`⚪ [NEW]`, `🔵 [WIP]`, `⏸️ [HOLD]`, `❓ [QUESTION]`, `✅ [DONE]`, `❌ [CANCELED]`).

## Resume

Written 2026-11-13. Released `run_block` `v0.12.0` (`d6d883b`):
- Unified `--agents [ITEM ... | -RULE | KEY=VAL | --list]` with a categorized `src/rules/{blocks,core,vcs,release,stack}/` directory hierarchy, removed `src/templates/`, and strengthened the mandatory `--fix` preference rule.
- Added deferred roadmap tasks `F7` (plugin system + LLM block analyzer + headless protocol mode) and `F8` (standalone `agents_bundle` project) to `TODO_PLAN.md`.
- Earlier in session: completed `F1`–`F6` (`v0.8.0`–`v0.11.0`).

## Tasks

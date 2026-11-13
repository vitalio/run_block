# run_block — active tasks and operational state

`README.md` documents installation and CLI usage; `AGENTS.md`
defines the rules and workflow for an AI agent working on this repository.

Task heading format: `### <emoji> [<STATUS>] <ID>: <title>`
(`⚪ [NEW]`, `🔵 [WIP]`, `⏸️ [HOLD]`, `❓ [QUESTION]`, `✅ [DONE]`, `❌ [CANCELED]`).

## Resume

Written 2026-11-13. Released `run_block` `v0.10.0` (`3514abe`):
- Renamed `--rules` to `--agents-rules` (keeping `--rules` as an alias), extracted `lang` as a standalone rule module, added `key=value` template variable substitution (`{var:default}`), and made `workflow` language-agnostic with the full 3-point `Self-reviewed diff before commit` rule.
- Updated `.run_block.start` and slimmed `AGENTS.md` in `run_block`, `~/todo_md`, and `~/chrome/canary`.
- Next in queue: `F6` (modularize `run_block` into `src/` + `build.py` bundler).

## Tasks

### ⚪ [NEW] F6: Modularize run_block source into src/ with build.py single-file bundler

Split monolithic run_block into src/ Python modules and src/templates/*.md + src/rules/*.md files, compiled into standalone ./run_block by build.py.

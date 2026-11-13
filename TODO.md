# run_block — active tasks and operational state

`README.md` documents installation and CLI usage; `AGENTS.md`
defines the rules and workflow for an AI agent working on this repository.

Task heading format: `### <emoji> [<STATUS>] <ID>: <title>`
(`⚪ [NEW]`, `🔵 [WIP]`, `⏸️ [HOLD]`, `❓ [QUESTION]`, `✅ [DONE]`, `❌ [CANCELED]`).

## Resume

Written 2026-11-13. Released `run_block` `v0.13.2`, `agents_bundle` `v0.3.0`, and `agents_rules` `v0.4.1`:
- Added `[if key=val]` / `[/if]` conditional directives and built-in variables (`os`, `vcs`) in `agents_bundle` (`v0.3.0`) and `agents_rules` (`v0.4.0`), replacing virtual `os/auto` and `vcs/auto` rules; added `-x`/`--exclude` and two-stage directory truncation to `agents_bundle --tree`.
- Refined `os/linux`, `os/macos`, and `core/plan` in `agents_rules` (`v0.4.1`) and `run_block --agents` (`v0.13.1`) to require batched multi-file reads and restrict `set -euo pipefail` to state-mutating/build/commit steps.
- Collapsed shell heredocs (`cat <<'EOF' > ...`), grouped operations by `cd` working directory, switched operation tags to lowercase (`[git]`, `[write]`, `[read]`, `[exec]`), and split `external-write` into `git-push` and `net-write` with `(in <dir>)` annotations in `run_block` (`v0.13.2`).
- Migrated `~/chrome/canary` to local gitignored `.agents_bundle` and removed bundled `run_block`/`todo_md` references from its tracked files.

## Tasks

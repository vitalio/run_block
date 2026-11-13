# run_block — active tasks and operational state

`README.md` documents installation and CLI usage; `AGENTS.md`
defines the rules and workflow for an AI agent working on this repository.

Task heading format: `### <emoji> [<STATUS>] <ID>: <title>`
(`⚪ [NEW]`, `🔵 [WIP]`, `⏸️ [HOLD]`, `❓ [QUESTION]`, `✅ [DONE]`, `❌ [CANCELED]`).

## Resume

Written 2026-11-13. Released `run_block` `v0.8.0` (`15f24a8`):
- Completed `F1`: native PowerShell (`pwsh` / `powershell`) block execution mode (`.ps1` scripts, AST syntax validation, and PowerShell here-string `--agents` instructions).
- Completed `F2`: custom safety scanner rules in config (`safety_disable` / `RUN_BLOCK_SAFETY_DISABLE` and `safety_rule.<category>` / `RUN_BLOCK_SAFETY_RULES`).
- Completed `F3`: session cleanup command (`run_block --clean [--keep N | --all] [--yes]`).
- Completed `F4`: smart token-budgeted repository map (`run_block --tree [DIR] [--max-lines N] [--max-tokens N]`), usable in `.run_block.start`.
- All active and planned tasks in `TODO.md` and `TODO_PLAN.md` are complete.

## Tasks

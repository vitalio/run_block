# run_block — deferred tasks and future roadmap

Active operational tasks live in `TODO.md`; completed and canceled records live in `TODO_ARCHIVE.md`.

## Deferred Tasks

### ⚪ [NEW] F7: Plugin architecture (pre/post hooks, LLM block analyzer, and headless stdout mode)

Add extensible plugin hooks for pre-execution block analysis (including LLM-based script review and auto-approval of safe blocks) and post-execution output handling (clipboard box vs raw stdout protocol mode).

### ⚪ [NEW] F9: Audit run_block and todo_md architecture against unix-philosophy.md

Review CLI flags, stdin/stdout/stderr separation, and composability of run_block and todo_md against core/unix-philosophy.md.

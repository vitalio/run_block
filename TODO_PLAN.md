# run_block — deferred tasks and future roadmap

Active operational tasks live in `TODO.md`; completed and canceled records live in `TODO_ARCHIVE.md`.

## Deferred Tasks

### ⚪ [NEW] F7: Plugin architecture (pre/post hooks, LLM block analyzer, and headless stdout mode)

Add extensible plugin hooks for pre-execution block analysis (including LLM-based script review and auto-approval of safe blocks) and post-execution output handling (clipboard box vs raw stdout protocol mode).

### ⚪ [NEW] F8: Extract context bundler and engineering rules catalog into standalone agents_bundle project

Move --start, .agents_bundle spec, --tree, and universal engineering rules/presets into a separate zero-dependency 'agents_bundle' CLI with zero hardcoded coupling to run_block (connected via user config and 'run_block --bundle').

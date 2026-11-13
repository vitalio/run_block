# run_block — archived tasks (DONE and CANCELED)

Active operational tasks live in `TODO.md`; deferred tasks live in `TODO_PLAN.md`.

## Archive

### ✅ [DONE] F1: Native PowerShell (`pwsh`) block execution mode on Windows — *15f24a8*

Allow `shell = pwsh` in `~/.config/run_block/config` so Windows users in PowerShell 7
can execute native PowerShell blocks in addition to Bash blocks.

### ✅ [DONE] F2: Custom user-defined safety rules in config — *15f24a8*

Allow adding custom regex patterns or overriding risk categories in
`~/.config/run_block/config`.

### ✅ [DONE] F3: Session cleanup command (`--clean`) — *15f24a8*

Add `run_block --clean [--keep N | --all]` to prune old session directories in
`/tmp/run_block`.

### ✅ [DONE] F4: Smart budget-aware repository map (--tree) — *15f24a8*

Add `run_block --tree` (usable in `.run_block.start` as `$ run_block --tree`) to generate a compact, token-budgeted repository file tree (respecting `.gitignore`, showing line counts for source files, and collapsing large directories into summaries instead of dumping thousands of paths).

### ✅ [DONE] F5: Modular agent rules knowledge base (--rules) — *f618c65*

Add 'run_block --rules [topic ... | all | --list]' with built-in topics (workflow, semver, python-cli) and user rules in ~/.config/run_block/rules/*.md.

### ✅ [DONE] F6: Modularize run_block source into src/ with build.py single-file bundler — *83863e7*

Split monolithic run_block into src/ Python modules and src/templates/*.md + src/rules/*.md files, compiled into standalone ./run_block by build.py.

### ✅ [DONE] F8: Extract context bundler and engineering rules catalog into standalone agents_bundle project — *99bc5e1*

Move --start, .agents_bundle spec, --tree, and universal engineering rules/presets into a separate zero-dependency 'agents_bundle' CLI with zero hardcoded coupling to run_block (connected via user config and 'run_block --bundle').

### ✅ [DONE] F7: Plugin architecture (pre/post hooks, LLM block analyzer, and headless stdout mode) — *412de9c*

Add extensible plugin hooks for pre-execution block analysis (including LLM-based script review and auto-approval of safe blocks) and post-execution output handling (clipboard box vs raw stdout protocol mode).

- Unify command classification ('[git]', '[write]', '[read]', '[exec]', '[python]') and safety risk scanning ('[git-push]', '[net-write]', '[git-destructive]', etc.) into the pre-execution analyzer plugin interface.

### ✅ [DONE] F9: Audit run_block and todo_md architecture against unix-philosophy.md — *412de9c*

Review CLI flags, stdin/stdout/stderr separation, and composability of run_block and todo_md against core/unix-philosophy.md.

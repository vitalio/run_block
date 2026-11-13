# `run_block` — Project-Specific Agent Rules

Universal workflow, language, Git, SemVer, Python CLI, and single-file build rules are loaded via `.agents_bundle`.

## Architecture & Module Boundaries

- `src/header.py` — CLI usage docstring, standard library imports, and version constants.
- `src/config.py` — zero-config environment variable settings (`RUN_BLOCK_*`, `VISUAL`/`EDITOR`) and working directory resolution.
- `src/agents.py` & `src/rules/blocks/*.md` — embedded Markdown instructions emitted by `run_block --agents`.
- `src/safety.py` — AST/regex operation classifier, safety risk scanner, `run_block --plan` JSON output, and `RUN_BLOCK_APPROVE_CMD` validator hook.
- `src/ui.py` — terminal TUI boxes (`BLOCK PLAN`, `START`, `END`), token statistics, and clipboard integration.
- `src/runner.py` — sequential session/step execution (`<session>/<step>`), `--fix` patching, `--retry`, `--list`, `--show`, `--clean`, and `-y`/`--yes` headless mode.
- `src/bundle.py` — session initialization (`agents_bundle | run_block` -> `<session>/0.txt`).
- `src/cli.py` — CLI argument routing and self-update (`--update`, `--check-update`).

# `run_block` — Project-Specific Agent Rules

Universal workflow, language, Git, SemVer, Python CLI, and single-file build rules are loaded via `$ run_block --agents-rules python-tool single-file-build`.

## Release trigger & local reinstall

- Edit source files under `src/` (`src/*.py`, `src/templates/*.md`, `src/rules/*.md`, `src/presets.txt`) and run `python3 build.py` to regenerate `./run_block`.
- Whenever `src/` (and thus `run_block`), `install.sh`, or `install.ps1` is modified, bump `VERSION` and `VERSION = "..."` in `src/header.py`, run `python3 build.py`, reinstall locally via `sh install.sh --yes >/dev/null`, commit, push to `origin main`, and push annotated tag `vX.Y.Z`.

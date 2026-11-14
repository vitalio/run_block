# 🎯 [NEXT] F10: Prompt injection defenses, safe --fix AST validator, and session Sandbox contract

- Validate `--fix` Python patch AST before `exec()` (allow only pure text/regex manipulation; reject imports, dunder access, and unsafe builtins).
- Protect `<session>/0.txt` integrity across block execution (in-memory snapshot + revert on tampering; read-only `BASE_DIR` inside OS sandboxes).
- Support `Sandbox:` header in `<session>/0.txt`, `RUN_BLOCK_SANDBOX` env setting, and `--sandbox` CLI command/flag (`off`, `strict`, `nonet`) with cross-platform secret env scrubbing, Linux `bwrap`, and macOS `sandbox-exec`.
- Enhance `src/safety.py` scanner (Python AST `subprocess`/`urllib`/`socket`/`eval`, paths outside `Workdir`, `.git/hooks`, and hidden Bidi/Zero-Width Unicode spoofing) and set `default_yes=False` when `RUN_BLOCK_APPROVE_CMD` exits `2`.

# ⚪ [NEW] F11: Support inserting intermediate blocks before an unexecuted or pending step

- Allow running an intermediate block when the model already emitted `<session>/<N>` in chat, but the user asks for another action first (e.g. `s28/9a` / `s28/8_pre` or seamless step re-sequencing without breaking the sequential step guard).

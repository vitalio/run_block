# 🔵 [WIP] B2: Fix BLOCK PLAN analyzer for backslash continuations, external paths, quoted echo, and multi-dir Python AST

- Join shell line continuations (trailing `\`) outside heredoc and Python blocks before classifying commands and scanning risks.
- Ignore `>` inside single or double quotes when filtering non-redirected `echo`/`printf` statements.
- Recognize absolute external paths under `$HOME` (e.g. `/home/<user>/<repo>/...`) and `*_CWD=/path` environment prefixes in `_infer_op_dir` so commands operating on sibling repositories are grouped under their target directory.
- In `_analyze_python_ast` and `_emit_py_op`, track loop target variables (`for x in (...):`), surface `Path.unlink()` / `Path.rmdir()` deletions (including `fs-destructive` risk warnings), and group or summarize Python file operations across all target directories without silently dropping paths past 12 items.

# 🎯 [NEXT] F11: Recursive step directory layout and intermediate sub-blocks (e.g. s28/8.1)

- Store each step in its own directory (`<session>/<step>/block.sh`, `out.txt`) so every step (top-level, intermediate sub-step, or fix) shares a uniform recursive structure.
- Support intermediate sub-blocks after an executed step `<N>` before `<N+1>` (e.g. `s28/8.1` -> `s28/8/1/`, `s28/8.1.1` -> `s28/8/1/1/`) and nested fixes (`fix_1/`), so an already-emitted `<session>/<N+1>` block in chat remains valid without reprinting.

- Handle repeated `--fix <session>/<step>` calls cleanly without failing with `fix step already exists` (auto-advance to the next fix slot or chain from the latest fix).

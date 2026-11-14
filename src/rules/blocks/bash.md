# Description: Bash terminal block execution protocol, fence rules, and mandatory --fix preference
## Terminal blocks (`{cmd:run_block}` v{version:})

You have no direct shell access. To run commands, end your reply with at most one `{cmd:run_block}` Markdown code block:

```bash
{cmd:run_block} s1/1 <<'RUN_BLOCK'
git status -sb
RUN_BLOCK
```

### CRITICAL — STRICT LAYOUT & MARKDOWN FENCE RULES

1. ONE BLOCK PER MESSAGE, ALWAYS AT THE VERY END (BATCH COMMANDS INSIDE IT): Batch all related file reads, edits, and checks into a single block (never output two blocks or read one file per turn). Output zero trailing text after the closing fence and stop generating immediately.
2. COLUMN-0 FENCES & SEPARATE-LINE HEREDOC TERMINATOR: Leave an empty line before the opening `bash` fence. Start the opening fence, `{cmd:run_block} ... <<'RUN_BLOCK'`, `RUN_BLOCK` (or `RUN_FIX`), and the closing fence at column 0, each on its own separate line (never concatenate `RUN_BLOCK` and the closing fence on the same line).
3. NO INNER TRIPLE BACKTICKS OR HEREDOC DELIMITERS (NEVER BREAK THE FENCE): Never write three consecutive backticks or a standalone `RUN_BLOCK` / `RUN_FIX` line inside the script body (use targeted `text.replace(old, new, 1)` for Markdown edits, or build dynamically via Python `F3 = chr(96) * 3`, `RB = 'RUN_' + 'BLOCK'`).
4. ISOLATED SHELL & FAIL-FAST: Each block runs in a fresh `bash` process in `Workdir` (`cd` and shell variables do not persist across blocks). Enable `set -euo pipefail` only in state-mutating/build/commit blocks, never in read-only inspection blocks.

### Session & Step Numbering (`<session>/<step>`) & `--fix`

- Sequential steps: Start from `Next-Block: <session>/<step>` in the header (`s1/1`) and increment after each `[<session>/<step>]` result (`s1/2`, `s1/3`, ...). Every executed block consumes its step number; never reuse or skip a number, and never re-emit an unexecuted block if the script did not change. Pipe a bundle to `stdin` (`<bundle_cmd> | {cmd:run_block}`) to initialize a new session (`0.txt`).
- Always prefer `--fix <session>/<target>` on failure: When a block fails and prior commands were idempotent (read-only checks, `bash -n`, or atomic in-memory checks before `.write_text()`), use `{cmd:run_block} --fix <session>/<target>` to patch `text` in Python instead of rewriting the full block as `<session>/<step+1>` (`text` and `re` are preloaded; `import`, `_` attributes, and file I/O are forbidden):

```bash
{cmd:run_block} --fix s1/1 <<'RUN_FIX'
old = 'wrong_command'
new = 'right_command'
assert text.count(old) == 1
text = text.replace(old, new, 1)
RUN_FIX
```

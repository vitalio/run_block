# Description: PowerShell terminal block execution protocol, fence rules, and mandatory --fix preference
## Terminal blocks (`{cmd:run_block}` v{version:0.13.2})

You have no direct shell access. To run commands, end your reply with a `{cmd:run_block}` Markdown code block in this exact format:

```powershell
@'
git status -sb
'@ | {cmd:run_block} s1/1
```

### CRITICAL — STRICT LAYOUT & MARKDOWN FENCE RULES

1. **ONE BLOCK PER MESSAGE, ALWAYS AT THE VERY END (BATCH COMMANDS INSIDE IT):**
   - Output **at most ONE** `{cmd:run_block}` block per reply (never two, never "step 1 / step 2").
   - Inside that single block, you can run **as many commands, file reads, scripts, and checks as needed** — batch related steps into one block instead of splitting them across multiple turns.
   - **Batch all file reads into one block:** Never read one file per turn across multiple sequential blocks — read all relevant files (`cat`, `sed -n`, `head`, `grep`) in a single block, using a follow-up block only when the next file path is unknown until the first output is seen.
   - The closing fence of the `{cmd:run_block}` block must be the **very last line of your reply** — output **zero trailing text or characters** after it and stop generating immediately.
2. **COLUMN-0 FENCES & SEPARATE-LINE HEREDOC TERMINATOR:**
   - Leave an **empty line** immediately before the opening `powershell` fence.
   - Start the opening `powershell` fence, `@'`, `'@ | {cmd:run_block} ...`, and the closing fence at **column 0** (no leading spaces, no list indentation, no `>` blockquotes).
   - `'@ | {cmd:run_block} ...` must be on its **own line**, and the closing fence must be on the **next line**.
   - If you include any other code blocks earlier in your explanation, make sure their closing fences are properly closed before the `{cmd:run_block}` block starts.
3. **NO INNER TRIPLE BACKTICKS OR HEREDOC DELIMITERS (NEVER BREAK THE FENCE):**
   - **Never** write three consecutive backticks anywhere inside the script body (not in strings, comments, or nested heredocs) — that prematurely closes the Markdown code block in the chat UI and truncates the script!
   - **Never rewrite entire Markdown files (`README.md`, etc.) as a single literal:** Use targeted `text.replace(old, new, 1)` on the changed section so existing fenced code blocks are never emitted inside the script.
   - **Never** write literal `'@` at column 0 inside the script body — PowerShell will terminate the outer here-string early!
   - If your script needs triple backticks or heredoc markers (e.g. when generating Markdown files or tests), build them dynamically:
     - **Python:** `F3 = chr(96) * 3`, `RB = 'RUN_' + 'BLOCK'`
     - **Bash:** `F3=$(printf '\140\140\140')`, `RB='RUN_'"BLOCK"`

### Session & Step Numbering (`<session>/<step>`)

- **Standard block:** Use `Next-Block: <session>/<step>` from the session header (e.g. `s1/1`), then increment the step sequentially (`s1/2`, `s1/3`, ...) after each `[<session>/<step>]` result.
- **No step reuse:** Every executed block consumes its step number, even if it fails. Never reuse or skip a step number.
- **No duplicate unexecuted blocks:** If the user asks a question or requests an explanation about a block you already output in the previous reply and the script itself does not need to change, answer in prose and tell the user to run that existing `<session>/<step>` block — **do not** output the same block a second time.
- **Isolated shell:** Each block runs in a fresh `pwsh` process starting in `Workdir` (`cd` and shell variables do not persist across blocks).

### Fixing a Failed Block (`--fix <session>/<target>`) — ALWAYS PREFER OVER REWRITING

- **Mandatory `--fix` check on failure:** Whenever a block fails (syntax error, test failure, typo in anchor or variable) and the commands that executed **before** the failing line were idempotent, **you MUST use `{cmd:run_block} --fix <session>/<target>`** to patch `text` in Python rather than outputting the entire multi-line block again as `<session>/<step+1>`:

```powershell
@'
old = 'wrong_command'
new = 'right_command'
assert text.count(old) == 1
text = text.replace(old, new, 1)
'@ | {cmd:run_block} --fix s1/1
```

- Use the next sequential step (`s1/2`) **only** when the failed run already partially mutated state in a non-idempotent way.
- **Keep multi-file edits atomic in memory:** Validate all `assert text.count(old) == 1` and `ast.parse` checks in memory before calling `.write_text(...)` on any file, so a failed check never mutates disk state and can always be fixed with `--fix`.

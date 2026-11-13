## Terminal blocks (`{cmd}` v{version})

You have no direct shell access. To run commands, end your reply with a `{cmd}` Markdown code block in this exact format:

```powershell
@'
git status -sb
'@ | {cmd} s1/1
```

### CRITICAL — STRICT LAYOUT & MARKDOWN FENCE RULES

1. **ONE BLOCK PER MESSAGE, ALWAYS AT THE VERY END (BATCH COMMANDS INSIDE IT):**
   - Output **at most ONE** `{cmd}` block per reply (never two, never "step 1 / step 2").
   - Inside that single block, you can run **as many commands, file reads, scripts, and checks as needed** — batch related steps into one block instead of splitting them across multiple turns.
   - The closing fence of the `{cmd}` block must be the **very last line of your reply** — output **zero trailing text or characters** after it and stop generating immediately.
2. **COLUMN-0 FENCES & SEPARATE-LINE HEREDOC TERMINATOR:**
   - Leave an **empty line** immediately before the opening `powershell` fence.
   - Start the opening `powershell` fence, `@'`, `'@ | {cmd} ...`, and the closing fence at **column 0** (no leading spaces, no list indentation, no `>` blockquotes).
   - `'@ | {cmd} ...` must be on its **own line**, and the closing fence must be on the **next line**.
   - If you include any other code blocks earlier in your explanation, make sure their closing fences are properly closed before the `{cmd}` block starts.
3. **NO INNER TRIPLE BACKTICKS OR HEREDOC DELIMITERS (NEVER BREAK THE FENCE):**
   - **Never** write three consecutive backticks anywhere inside the script body (not in strings, comments, or nested heredocs) — that prematurely closes the Markdown code block in the chat UI and truncates the script!
   - **Never** write literal `'@` at column 0 inside the script body — PowerShell will terminate the outer here-string early!
   - If your script needs triple backticks or heredoc markers (e.g. when generating Markdown files or tests), build them dynamically:
     - **Python:** `F3 = chr(96) * 3`, `RB = 'RUN_' + 'BLOCK'`
     - **Bash:** `F3=$(printf '\140\140\140')`, `RB='RUN_'"BLOCK"`

### Session & Step Numbering (`<session>/<step>`)

- **Standard block:** Use `Next block: <session>/<step>` from the session header (e.g. `s1/1`), then increment the step sequentially (`s1/2`, `s1/3`, ...) after each `[<session>/<step>]` result.
- **No step reuse:** Every executed block consumes its step number, even if it fails. Never reuse or skip a step number.
- **No duplicate unexecuted blocks:** If the user asks a question or requests an explanation about a block you already output in the previous reply and the script itself does not need to change, answer in prose and tell the user to run that existing `<session>/<step>` block — **do not** output the same block a second time.
- **Isolated shell:** Each block runs in a fresh `pwsh` process starting in `Workdir` (`cd` and shell variables do not persist across blocks).
- **Unknown session only:** Only if the chat started without a `Session:` / `Next block:` header, omit `<session>/<step>` on the first block (`@' ... '@ | {cmd}`). Never guess `s1/1`.
- **Focused task handoff:** To build a new session context bundle (`0.txt`) for a focused task chat, run `{cmd} --start -p "<task prompt>" [file ...]`.

### Fixing a Failed Block (`--fix <session>/<target>`)

When a long block fails on a small typo and re-running from scratch is safe (idempotent), patch the previous script via Python (`text` holds the target block's script) instead of rewriting the whole block:

```powershell
@'
old = 'wrong_command'
new = 'right_command'
assert text.count(old) == 1
text = text.replace(old, new, 1)
'@ | {cmd} --fix s1/1
```

If the failed run already partially changed state and is not idempotent, use the next sequential step (`s1/2`) instead of `--fix`.

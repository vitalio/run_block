# run_block

**Safe, sequential terminal block execution protocol for AI coding agents.**

`run_block` is a zero-dependency Python 3 CLI that connects any chat LLM to your local
terminal without API keys or background daemons. It receives a session context bundle on `stdin`
(`agents_bundle | run_block --start` -> `/tmp/run_block/<session>/0.txt`) and executes numbered
Bash or PowerShell blocks (`<session>/1`, `<session>/2`, ...) with syntax validation, a
pre-execution `BLOCK PLAN` safety scanner, PTY streaming, and one-keystroke clipboard copy
with Claude/GPT/Gemini token counts.

## Quick Installation

### Linux & macOS

```bash
curl -fsSL https://raw.githubusercontent.com/vitalio/run_block/main/install.sh | sh
```

### Windows (PowerShell 7+)

```powershell
irm https://raw.githubusercontent.com/vitalio/run_block/main/install.ps1 | iex
```

## Starting a Session (`agents_bundle | run_block --start`)

Pipe any context bundle (for example from `agents_bundle`) into `run_block --start` to initialize
`/tmp/run_block/<session>/0.txt` and copy it to your clipboard:

```bash
agents_bundle | run_block --start
agents_bundle -p "Let's work on task F7" src/runner.py | run_block --start
```

## Running and Fixing Blocks

### 1. First block (auto-initializes session if omitted)

```bash
run_block <<'RUN_BLOCK'
git status -sb
RUN_BLOCK
```

### 2. Subsequent numbered blocks (`<session>/<step>`)

```bash
run_block s1/2 <<'RUN_BLOCK'
python3 -m unittest
RUN_BLOCK
```

Before running, `run_block` displays the `BLOCK PLAN` (working directory, operations, and
any safety warnings). Press `Enter`/`y` to run, `n`/`Esc` to abort, or `v` to inspect the
script in your terminal editor.

### 3. Patching a failed block (`--fix`)

```bash
run_block --fix s1/2 <<'RUN_FIX'
old = 'wrong_arg'
new = 'right_arg'
assert text.count(old) == 1
text = text.replace(old, new, 1)
RUN_FIX
```

## Environment Variables

`run_block` works out of the box with zero configuration files and honors standard environment variables:

| Environment Variable | Default | Description |
| :--- | :--- | :--- |
| `RUN_BLOCK_DIR` | `/tmp/run_block` | Directory where session `<step>.sh` and `<step>.txt` files are stored |
| `RUN_BLOCK_CWD` | `auto` | `auto` (Git root or `$PWD`), `cwd` (always `$PWD`), or explicit path |
| `RUN_BLOCK_CLIPBOARD` | `prompt` | `prompt` (`Enter`/`Esc` box), `auto` (copy automatically), `never` |
| `RUN_BLOCK_HEADLESS` | `0` | Set to `1` (or pass `-y`/`--yes`) for raw stdout protocol without TUI boxes |
| `RUN_BLOCK_APPROVE_CMD` | *(none)* | External/LLM validator command receiving `--plan` JSON on `stdin` (`0`=approve, `2`=prompt user with stdout note, other=reject) |
| `RUN_BLOCK_TOKEN_STATS` | `true` | Show byte size and Claude/GPT/Gemini token counts (`true` / `false`) |
| `RUN_BLOCK_SHELL` | `bash` | Shell binary (`bash`, `sh`, or `pwsh`/`powershell` on Windows) |
| `VISUAL` / `EDITOR` | `vim`/`less`/`nano` | Terminal editor/viewer for `v` in `BLOCK PLAN` |
| `RUN_BLOCK_SAFETY_DISABLE` | *(none)* | Comma-separated built-in risk categories to disable |
| `RUN_BLOCK_SAFETY_RULES` | *(none)* | Semicolon-separated `<cat>=<regex>` rules |

## CLI Reference

| Command | Description |
| :--- | :--- |
| `run_block [-y] [<session>/<step>]` | Run a block from `stdin` (`-y` for non-interactive headless mode) |
| `run_block --plan` | Analyze script from `stdin` and print JSON execution and safety plan |
| `run_block --fix [-y] <session>/<target>` | Patch `<target>` script via Python on `stdin` and run as `<target>_N` |
| `run_block --retry [-y] [session/step]` | Re-run the last (or specified) block |
| `run_block --list`, `-l [session]` | List sessions and blocks with their status and summary |
| `run_block --show [session/step]` | Show saved script and output of a block (or `<session>/0` bundle) |
| `run_block --clean [--keep N \| --all]` | Prune old session directories in `/tmp/run_block` (default: `--keep 5`) |
| `run_block --start [--session NAME]` | Read context bundle from `stdin` into `<session>/0.txt` |
| `run_block --agents` | Print Markdown instructions for AI agents |
| `run_block --update [--force]` | Self-update `run_block` from GitHub (`vitalio/run_block`) |
| `run_block --check-update` | Check GitHub for a newer version |
| `run_block -V`, `--version` | Print version and exit `0` |
| `run_block -h`, `--help` | Print usage help and exit `0` |

## License

[MIT](LICENSE) © 2026 [vitalio](https://github.com/vitalio)

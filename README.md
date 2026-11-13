# run_block

**Safe, sequential terminal block execution and session context bundler for AI coding agents.**

`run_block` is a zero-dependency Python 3 CLI that connects any chat LLM to your local
terminal without API keys or background daemons. It builds a single-file session context
bundle (`run_block --start` -> `/tmp/run_block/<session>/0.txt`) and executes numbered
Bash blocks (`<session>/1`, `<session>/2`, ...) with `bash -n` syntax validation, a
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

## Starting a Session (`.run_block.start`)

Create `.run_block.start` in your project root (or run `run_block --init-start`).
Plain lines are UTF-8 file paths; lines starting with `$ ` are shell commands:

```text
$ run_block --agents python-tool

AGENTS.md

$ git status -sb
$ git branch -vv
$ git log --oneline -10
```

Build `/tmp/run_block/<session>/0.txt` and copy it to your clipboard:

```bash
run_block --start
run_block --start src/main.py -p "Let's work on task F1"
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

## Configuration (`~/.config/run_block/config`)

Run `run_block --init-config` to create `~/.config/run_block/config` or `run_block --config` to inspect active settings:

| Config Key | Environment Variable | Default | Description |
| :--- | :--- | :--- | :--- |
| `base_dir` | `RUN_BLOCK_DIR` | `/tmp/run_block` | Directory where session `<step>.sh` and `<step>.txt` files are stored |
| `work_dir` | `RUN_BLOCK_CWD` | `auto` | `auto` (Git root or `$PWD`), `cwd` (always `$PWD`), or explicit path |
| `clipboard` | `RUN_BLOCK_CLIPBOARD` | `prompt` | `prompt` (`Enter`/`Esc` box), `auto` (copy automatically), `never` |
| `token_stats` | `RUN_BLOCK_TOKEN_STATS` | `true` | Show byte size and Claude/GPT/Gemini token counts (`true` / `false`) |
| `shell` | `RUN_BLOCK_SHELL` | `bash` | Shell binary (`bash`, `sh`, or `pwsh`/`powershell` on Windows) |
| `editor` | `RUN_BLOCK_EDITOR` | `auto` | Terminal editor/viewer for `v` in `BLOCK PLAN` (`auto`, `nano`, `vim`, `less`) |
| `safety_disable` | `RUN_BLOCK_SAFETY_DISABLE` | *(none)* | Comma-separated built-in risk categories to disable |
| `safety_rule.<cat>` | `RUN_BLOCK_SAFETY_RULES` | *(none)* | Custom regex rule (or override) for risk category `<cat>` |

## CLI Reference

| Command | Description |
| :--- | :--- |
| `run_block [<session>/<step>]` | Run a Bash block from `stdin` (omit ref on first block to auto-init `<session>/1`) |
| `run_block --fix <session>/<target>` | Patch `<target>.sh` via Python on `stdin` and run as `<target>_N` |
| `run_block --retry [session/step]` | Re-run the last (or specified) block |
| `run_block --list`, `-l [session]` | List sessions and blocks with their status and summary |
| `run_block --show [session/step]` | Show saved script and output of a block (or `<session>/0` bundle) |
| `run_block --clean [--keep N \| --all]` | Prune old session directories in `/tmp/run_block` (default: `--keep 5`) |
| `run_block --tree [DIR] [options]` | Print token-budgeted repository file tree (`--max-lines N`, `--max-tokens N`) |
| `run_block --start [options] [FILE ..]` | Build `<session>/0.txt` context bundle from `.run_block.start` |
| `run_block --init-start [--force]` | Create a starter `.run_block.start` in the current directory |
| `run_block --agents [ITEM ... \| --list]` | Print AI agent instructions, presets, and rules (`default`, `blocks`, `workflow`, `python-tool`, `-rule`, `k=v`) |
| `run_block --config` | Show active configuration and sources |
| `run_block --init-config [--force]` | Create default `~/.config/run_block/config` |
| `run_block --update [--force]` | Self-update `run_block` from GitHub (`vitalio/run_block`) |
| `run_block --check-update` | Check GitHub for a newer version |
| `run_block -V`, `--version` | Print version and exit `0` |
| `run_block -h`, `--help` | Print usage help and exit `0` |

## License

[MIT](LICENSE) © 2026 [vitalio](https://github.com/vitalio)

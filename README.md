# run_block

**Write code, run tests, and build software directly through any AI chat window — with zero model API keys.**

**Your AI model writes the code right in your chat window — `run_block` gives it a transparent,
safe execution contract with your local terminal.**

You don't need paid model API access, API keys, background daemons, or heavy IDE plugins.
`run_block` builds a complete session context bundle (`run_block --start`) and operational contract (`run_block --agents`) for any
chat LLM (ChatGPT, Claude, Gemini, DeepSeek, etc.). Following that contract, the model proposes
one numbered Bash block at a time (`s1/1`, `s1/2`, ...). You paste it into your terminal, and
`run_block` validates syntax (`bash -n`), runs a **Pre-Execution Safety Check** (pausing for
confirmation if risky commands are detected), executes the block, logs clean output, shows byte
size and token counts, and copies the result back to your clipboard with a single `Enter`.

## Table of Contents

- [Why `run_block`?](#-why-run_block)
- [One-Line Installation](#-one-line-installation)
  - [Linux & macOS](#linux--macos)
  - [Windows (PowerShell)](#windows-powershell)
- [Giving Instructions to Your AI Model](#-giving-instructions-to-your-ai-model)
- [How It Works (Quick Start)](#️-how-it-works-quick-start)
  - [1. Start a session](#1-start-a-session-optional--auto-created-on-first-step)
  - [2. Run a block given by the AI agent](#2-run-a-block-given-by-the-ai-agent)
  - [3. Fix a failed block with `--fix`](#3-fix-a-failed-block-with---fix)
- [Pre-Execution Safety Check](#️-pre-execution-safety-check)
- [Configuration (`~/.config/run_block/config`)](#️-configuration-configrun_blockconfig)
- [Versioning & Self-Update](#-versioning--self-update)
- [CLI Reference](#-cli-reference)
- [License](#-license)

---

## ✨ Why `run_block`?

- **Code Directly from Any Chat Window (No API Keys Needed):** Use your existing web chat subscription to develop locally on any repository.
- **Zero External Dependencies:** Pure Python 3 standard library + Bash. Installs in seconds and runs anywhere without virtualenvs or `pip` setup.
- **Pre-Execution Safety Scanner (`confirm = risky`):** Automatically scans scripts before execution for destructive Git commands (`git reset --hard`, `git push --force`), recursive deletions (`rm -rf`, `shutil.rmtree`), `sudo`, remote writes, and secret exposure — pausing for explicit `[y/N]` confirmation when a risk is spotted.
- **Pre-Flight Syntax Validation:** Runs `bash -n` before executing a single command. Syntax errors are caught before touching your working tree.
- **Sequential Step Guardrails:** Enforces strict step numbering (`s1/1`, `s1/2`, `s1/3`). Refuses to accidentally re-run an old block or skip a step.
- **Surgical `--fix` Protocol:** When a long script fails on a typo, the agent sends a compact Python patch (`--fix s1/2`) instead of regenerating the entire block. `run_block` prints a unified diff and runs `s1/2_1`.
- **Live PTY Streaming + Clean Logs:** Streams live colors and progress bars to your terminal while stripping ANSI escapes and `\r` progress noise from the saved log (`/tmp/run_block/<session>/<step>.txt`).
- **Built-in Token & Size Telemetry:** Displays exact byte size and token counts for **Claude**, **GPT**, and **Gemini** before copying to the clipboard.
- **Declarative Session Context Bundler (`--start` & `.run_block.start`):** Assembles project files (`AGENTS.md`, `TODO.md`), dynamic tool instructions (`$ run_block --agents`, `$ todo_md --agents`), and Git state into `/tmp/run_block/<session>/0.txt` with token counts and one-keystroke clipboard copy.

---

## 🚀 One-Line Installation

Run the command for your platform in your terminal. The installer:
1. Verifies `python3` and `bash` are available.
2. Checks whether `run_block` is already used by another tool in your `PATH` (and lets you pick an alternative command name such as `run_term_block` if there is a conflict).
3. Installs the executable into `~/.local/bin`.
4. Prints the ready-to-paste instructions for your AI model (`AGENTS.md` / `CLAUDE.md`).

### Linux & macOS

```bash
curl -fsSL https://raw.githubusercontent.com/vitalio/run_block/main/install.sh | sh
```

**Custom command name or directory (optional):**

```bash
# Install as 'run_term_block' instead of 'run_block':
curl -fsSL https://raw.githubusercontent.com/vitalio/run_block/main/install.sh | sh -s -- --name run_term_block

# Install into /usr/local/bin:
curl -fsSL https://raw.githubusercontent.com/vitalio/run_block/main/install.sh | sh -s -- --dir /usr/local/bin
```

### Windows (PowerShell 7+)

Requires **PowerShell 7 (`pwsh`)**, **Python 3.10+**, and **Git for Windows** (`bash` in `PATH`):

```powershell
irm https://raw.githubusercontent.com/vitalio/run_block/main/install.ps1 | iex
```

---

## 🤖 Starting a Session & Giving Instructions to Your AI Model

Create a `.run_block.start` file in your project root (or generate a starter one with `run_block --init-start`):

```text
# Plain lines are UTF-8 file paths; lines starting with '$ ' are shell commands
AGENTS.md
TODO.md

$ run_block --agents
$ git status -sb
$ git branch -vv
$ git log --oneline -10
```

Then build the session context bundle (`/tmp/run_block/<session>/0.txt`) and copy it to your clipboard:

```bash
# Build 0.txt from .run_block.start (plus optional extra files and prompt):
run_block --start
run_block --start src/main.py -p "Let's implement feature X"

# Or print only the Markdown instructions for AI agents to stdout:
run_block --agents
```

---
## 🛠️ How It Works (Quick Start)

### 1. Start a session (or let the first block initialize it automatically)

```bash
# Option A: Build a context bundle (/tmp/run_block/s1/0.txt) for a new chat:
run_block --start

# Option B: If you started a chat without --start, the agent omits <session>/<step>
# on the first block and run_block automatically initializes the session as <session>/1:
run_block <<'RUN_BLOCK'
git status -sb
uname -a
RUN_BLOCK
```

### 2. Run subsequent blocks given by the AI agent

Once the session ID (`s1`) is known, the agent gives numbered blocks (`s1/2`, `s1/3`, ...):

```bash
run_block s1/2 <<'RUN_BLOCK'
python3 -m unittest
RUN_BLOCK
```

When you paste it into your terminal, `run_block`:
- Saves `/tmp/run_block/s1/1.sh` (`0600` permissions)
- Checks syntax with `bash -n` and scans for risky commands
- Executes the script from your current Git repository root (or current directory)
- Saves clean output to `/tmp/run_block/s1/1.txt`
- Prompts to copy `/tmp/run_block/s1/1.txt` to your clipboard:

```text
┌─ [s1/1] END (exit 0) ────────────────────────────────────────────┐
│ Size: 184 bytes | Tokens: Claude ~53 | GPT ~46 | Gemini ~46      │
│ -> Press Enter to copy /tmp/run_block/s1/1.txt to clipboard (Esc to skip) │
└──────────────────────────────────────────────────────────────────┘
```

### 3. Fix a failed block with `--fix`

If step `s1/2` fails due to a small mistake, the agent can patch `2.sh` without resending the whole script:

```bash
run_block --fix s1/2 <<'RUN_FIX'
old = 'pytest test_old.py'
new = 'pytest test_new.py'
assert text.count(old) == 1
text = text.replace(old, new, 1)
RUN_FIX
```

`run_block` saves `2_1.fix` and `2_1.sh`, prints the unified diff, checks `bash -n` and safety, and runs `s1/2_1`.

---

## 🛡️ Pre-Execution Safety Check

By default (`confirm = risky`), routine read/edit/test blocks run immediately, while potentially
dangerous operations pause **before execution** and display a warning box:

```text
┌─ [s1/4] [!] BLOCK PLAN (2 safety warnings) ─────────────────────────┐
│ Actions (3 lines, bash):                                            │
│   Write/Edit : rm -rf build_output/                                 │
│   Git        : git push --force origin main                         │
│                                                                     │
│ Safety warnings:                                                    │
│   [fs-destructive]   rm -rf build_output/                           │
│   [git-destructive]  git push --force origin main                   │
│                                                                     │
│ -> Execute this block? [y/N]:                                       │
└─────────────────────────────────────────────────────────────────────┘
```

- **Safe default (`[y/N]`):** Pressing `Enter` or `n` aborts execution immediately and removes the step's `.sh` file so the step number (`s1/4`) is **not consumed**.
- **6 Built-in Risk Categories:**
  1. `git-destructive` — `git reset --hard`, `git clean -f`, `git push --force`, `git branch -D`, `git checkout -- .`, `git rebase`
  2. `external-write` — `git push`, `curl`/`wget` with `POST`/`PUT`/`DELETE`/`PATCH`/`--data`, `scp`, `rsync`
  3. `fs-destructive` — `rm -rf`/`rm -r`, `shutil.rmtree()`, `os.remove()`, `dd of=...`, `mkfs`, overwriting `/etc/` or `~/.ssh/`
  4. `privilege-system` — `sudo`, `su`, `chmod 777`, `chown`, `systemctl`, `kill -9`, `apt`/`brew`/`pip install`
  5. `secrets-exposure` — `set -x`/`bash -x`, accessing private SSH keys (`~/.ssh/id_*`), `.netrc`, `.aws/credentials`
  6. `remote-exec` — `curl ... | sh`, `wget ... | bash`, `eval`

---

## ⚙️ Configuration (`~/.config/run_block/config`)

You can customize `run_block` via `~/.config/run_block/config` (or `$RUN_BLOCK_CONFIG`).

Generate a commented config file with defaults:

```bash
run_block --init-config
```

Inspect active settings and where each value comes from (`default`, `config`, or `env`):

```bash
run_block --config
```

### Supported Config Keys & Environment Variables

| Config Key | Environment Variable | Default | Options / Description |
| :--- | :--- | :--- | :--- |
| `base_dir` | `RUN_BLOCK_DIR` | `/tmp/<cmd>` | Directory where session `<step>.sh` and `<step>.txt` files are saved |
| `work_dir` | `RUN_BLOCK_CWD` | `auto` | `auto` (Git repo root or `$PWD`), `cwd` (always `$PWD`), or an explicit path |
| `clipboard` | `RUN_BLOCK_CLIPBOARD` | `prompt` | `prompt` (interactive `[Y/n]` box), `auto` (copy automatically), `never` (or `RUN_BLOCK_NO_CLIPBOARD=1`) |
| `token_stats` | `RUN_BLOCK_TOKEN_STATS` | `true` | `true` or `false` — show byte size and Claude/GPT/Gemini token counts |
| `shell` | `RUN_BLOCK_SHELL` | `bash` | Shell binary used for `bash -n` syntax check and execution |
| `update_url` | `RUN_BLOCK_UPDATE_URL` | GitHub raw URL | URL used by `--check-update` and `--update` |

---

## 🔄 Versioning & Self-Update

Check your installed version:

```bash
run_block --version
```

Check if a newer release is available on GitHub:

```bash
run_block --check-update
```

Update in place (preserves your custom command name and installation directory, and automatically prints the latest versioned agent instructions so you can verify your `AGENTS.md` / `CLAUDE.md`):

```bash
run_block --update
```

---

## 📖 CLI Reference

| Command / Flag | Description |
| :--- | :--- |
| `run_block [<session>/<step>]` | Read a Bash script from `stdin` (omit ref on first block to auto-init `<session>/1`) |
| `run_block --fix <session>/<target>` | Apply a Python patch from `stdin` to `<target>.sh` and run as `<target>_N` |
| `run_block --retry [session/step]` | Re-run the last block (or a specified block, e.g. after aborting) |
| `run_block --list`, `-l [session]` | List sessions and recent blocks with their status and summary |
| `run_block --show [session/step]` | Show the saved script and output of the last (or specified) block (including `<session>/0`) |
| `run_block --start [options] [FILE ...]` | Create a new session and build `<session>/0.txt` from `.run_block.start` |
| `run_block --init-start [--force]` | Create a starter `.run_block.start` file in the current directory |
| `run_block --config` | Show active configuration values and their sources |
| `run_block --init-config [--force]` | Create `~/.config/run_block/config` with commented defaults |
| `run_block --agents` | Print Markdown instructions for AI agents to `stdout` |
| `run_block --check-update` | Check GitHub (`vitalio/run_block`) for a newer version |
| `run_block --update [--force]` | Self-update the installed binary in place and print updated agent instructions |
| `run_block -V`, `--version` | Print version and exit `0` |
| `run_block -h`, `--help` | Print usage help and exit `0` |

---

## 📄 License

[MIT](LICENSE) © 2026 [vitalio](https://github.com/vitalio)

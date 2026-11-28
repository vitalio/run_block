# run-block (`run`)

**Safe, sequential terminal block execution protocol for AI coding agents.**

`run` (`vitalio/run-block`) is a zero-dependency Python 3 CLI that connects any
chat LLM to your local terminal without API keys or background daemons. It
initializes a rule-only session on bare TTY invocation (`run`) or ingests a
context bundle on `stdin` (`<command> | run` ->
`~/.local/state/run-block/<session>/0`), then executes numbered Bash blocks
(`<session>/1`, `<session>/2`, ...) with syntax validation, an AST/regex safety
scanner, PTY streaming, interactive TUI cards with a fullscreen `i(nfo)`
inspector, targeted `--fix` patching, and one-keystroke clipboard handoff with
Claude/GPT/Gemini token counts.

## Quick Installation

```bash
curl -fsSL https://raw.githubusercontent.com/vitalio/run-block/main/install.sh | sh
```

## Quick Start

### 1. Start a session (`run` or `<cmd> | run`)

```bash
run
run -p "Investigate failing test"
cat context.txt | run -p "Focus on edge cases"
run --start --session s1 -p "Implement feature" < context.txt
```

Run bare `run` (or `run --start`) in an interactive TTY to create a
rule-only `<session>/0` bundle with embedded `bash` rules, or pipe any
context bundle on `stdin` to inject rules and copy `<session>/0` to the
clipboard. Repeatable `-p TEXT` / `--prompt TEXT` flags append prompt sections
to `===== Prompt =====` (joining multiple non-empty values with `\n\n`).

### 2. Run numbered blocks (`<session>/<step>`) or full replies (`-r` / `--run`)

```bash
run s1/1 <<'RUN_BLOCK'
git status -sb
python3 -m unittest
RUN_BLOCK

run -rc
run -r --clipboard s1
run -r
wl-paste | run -r s1
```

With `run -r [-c] [session]` / `run --run [--clipboard] [session]` (or shorthand
`run -rc [session]`), you can ingest an entire model reply (reasoning prose +
code block): with `-c` / `--clipboard`, `run` reads directly from the system
clipboard (`wl-paste`, `xclip`, `xsel`, `pbpaste`, or `powershell.exe`); when
`stdin` is a TTY without `-c`, `run -r` opens a temporary buffer in `$VISUAL` /
`$EDITOR`; when piped, it reads from `stdin`. Replies are validated before
allocating `<session>/<step>/` on disk, so accidental invocations with plain
clipboard text fail cleanly with zero orphan step directories. It automatically
extracts the first actionable `RUN_BLOCK` or
`--fix` / `RUN_FIX` block (matching `[session]` when given, preserving nested
doc/heredoc examples, and discarding any trailing hallucinated output or
subsequent blocks), repairs split fences or missing terminators, preserves
explicit block step numbers (or infers `next_free_step()` when omitted) so
repeated runs hit duplicate guards, and persists the model's preceding prose in
`<session>/<step>/meta.json` and `plan.md`.

Before execution, `START STEP` displays the model's `Reasoning:` commentary (if
present), the resolved working directory, numbered operations (with
AST-expanded Python sub-items), and any safety warnings. During execution, live `[N/M]` progress markers and per-operation
timings stream to the terminal, and `END STEP` offers one-keystroke clipboard
copy of the combined step header, output, and token stats.

### 3. Patch a failed block (`--fix`)

```bash
run --fix s1/1 <<'RUN_FIX'
old = 'wrong_arg'
new = 'right_arg'
assert text.count(old) == 1
text = text.replace(old, new, 1)
RUN_FIX
```

Use `--fix <session>/<target>` for small, targeted patches to a failed step
(`text` and `re` are preloaded; targeting `<base>` allocates `<base>_1`, and
chaining `--fix <base>_1` allocates `<base>_2`, up to
`RUN_BLOCK_MAX_FIX_ATTEMPTS`). When a fix requires rewriting
multiple sections, emit a fresh `<session>/<step+1>` block instead.

### 4. Complete a session (`--done`)

```bash
run --done s1 -m "Completed feature and tests"
```

`--done` persists completion metadata (`completed`, `completed_at`,
`completed_note`) and accumulated step statistics in `<session>/meta.json` and
renders the `END SESSION` summary card (`--list` marks completed sessions with
`[DONE]`). Inside a running step (`IN_RUN_BLOCK=1`), `--done` queues a deferred
`END SESSION` card after the outer `END STEP`, while nested session
initialization (`--start` or piped bundles) and step execution are rejected
with exit status `2`.

### 5. Persist settings and model profiles (`--config`, `-P`)

```bash
run --config                      # settings with sources, profiles, roles
run --config pager=less           # persist a setting in config.json (0600)
run --config profiles.opus.provider=anthropic
<command> | run -P opus           # start a session pinned to a profile
```

## Interactive TUI & Keyboard Shortcuts

All inline TUI cards clamp overflowing sections to the visible terminal height
(`... +N more`), wrap long lines with `│ ` borders, and automatically redraw in
place on terminal resize (`SIGWINCH`). Bracketed prompts highlight the `Enter`
default in uppercase (`[Y/n]`, `[y/N]`), while `START STEP` safety warnings use
lowercase `[y/n/i(nfo)]:` and require an explicit `y` or `n`.

### TUI Cards & Confirmation Prompts

| TUI Card / Prompt | Prompt Format | Behavior & Options |
| :--- | :--- | :--- |
| `START SESSION` | `[Y/n/p(rompt)/i(nfo)]:` | Copy initialized `<session>/0` bundle to clipboard, append a `p(rompt)` note, or inspect bundle parts in `i(nfo)` |
| `START STEP` (clean) | `[Y/n/i(nfo)]:` | `Enter`/`y` runs the block; `n`/`Esc` aborts (`NOT RUN`); `i` opens pre-execution plan and script editor |
| `START STEP` (warning) | `[y/n/i(nfo)]:` | `Enter` is ignored when safety warnings or approval prompts exist; requires explicit `y`, `n`/`Esc`, or `i` |
| `END STEP` / `SYNTAX ERROR` / `NOT RUN` | `[Y/n/p(rompt)/i(nfo)]:` | Copy formatted `[<session>/<step>]` result to clipboard, append a trailing `p(rompt)` note to `out`, or open `i(nfo)` |
| `END SESSION` | *(summary card)* | Displays session completion note, step counts (ok/failed/`--fix`/renumbered), and total duration |
| `STEP ALREADY EXISTS` | `[Y/n/r(enumber)/i(nfo)]:` | Copy existing `out` (`[r(enumber)/n/i(nfo)]:` when `out` is absent), `r(enumber)` to the next free step, or overwrite via `i(nfo)` |
| `MISSING PREVIOUS STEP` | `[r(enumber)/n/i(nfo)]:` | `r(enumber)` block to the first missing sequential step number, cancel with `n`/`Esc`, or inspect in `i(nfo)` |
| `SESSION COMPLETED` | `[y/N/i(nfo)]:` | Shown before running a block on a completed session (default `No`); `y` (or `-y`/`--yes`) clears completion and reopens |
| `CLEAN SESSIONS` | `[y/N]:` | Confirm pruning target sessions during interactive `run --clean` |

### Prompt Action Keys

| Key | Action |
| :--- | :--- |
| `Enter` / `y` | Accept the uppercase default action (run clean step or copy output/bundle to clipboard) |
| `n` / `Esc` | Cancel or skip the current prompt without proceeding |
| `p` (`p(rompt)`) | Open a temporary `.md` file in `$VISUAL`/`$EDITOR` and append saved text to `===== Prompt =====` in `<session>/0` or step `out` (preserving `0.orig` / `out.orig`) |
| `r` (`r(enumber)`) | Renumber a colliding or out-of-order block to the expected sequential `<session>/<step>` and record a notice in `out` |
| `i` (`i(nfo)`) | Open the borderless alternate-screen fullscreen metadata and artifact inspector |

### Fullscreen `i(nfo)` Inspector Shortcuts

| Key | Context | Action |
| :--- | :--- | :--- |
| `Up`/`Down`, `j`/`k`, `PgUp`/`PgDn` | All `i(nfo)` views | Scroll the fullscreen report vertically (the footer shows `Lines a-b/N` and the scroll hint only when the body overflows) |
| `Tab` (`Tab: parts`) | `START SESSION` `i(nfo)` | Toggle the row selection cursor across sequential numbered bundle rows `1..M` (`[bundle]` folders and leaf parts) |
| `Tab` (`Tab: parts`) | Step `i(nfo)` (`START STEP`, `END STEP`, `SYNTAX ERROR`, `NOT RUN`, `STEP ALREADY EXISTS`) | Toggle the row selection cursor across the numbered operation rows `1..N` of the breakdown table (`START STEP`: pre-execution script table; `END STEP`: output table with `TIME`) |
| `Enter` (in `Tab` cursor) | `START SESSION` `i(nfo)` | Open `PART N/M` for a leaf part or `BUNDLE R/M` (with constituent part delimiters) for a `[bundle]` folder row |
| `Enter` (in `Tab` cursor) | Step `i(nfo)` | Open `PART k/N` for the selected operation: `Command`, `Timing`, `Script-Range`, and `Range: lines a-b of <out>` with the operation's captured output slice from `<step>/out` (script lines in `START STEP` or without `out`); `n`/`N` step across operations, `e`/`o` edit `out`, `s` edits the script, `m` opens `meta.json` |
| `n` / `N` | `PART` / `BUNDLE` viewer | Step forward or backward across sequential numbered rows `1..M` |
| `e` (`e(dit)`) | `START SESSION` / `START STEP` | Edit `<session>/0.raw` (preserving boundary markup and `0.orig`) or `block.sh` (`block.orig.sh`) and re-parse in place |
| `s` (`s(cript)`) / `o` (`o(utput)`) | Step `i(nfo)` views | Edit saved block script or captured step output in `$VISUAL`/`$EDITOR` (preserving `*.orig` backups and updating stats) |
| `O` / `o` (`overwrite`) | `STEP ALREADY EXISTS` `i(nfo)` | Overwrite the existing step directory and proceed with the new block |
| `p` (`p(rompt)`) | Copyable `i(nfo)` views | Append a prompt or output note via `$VISUAL`/`$EDITOR` and recalculate token stats |
| `v` (`v(iew)`) | All `i(nfo)` views | Open the plain-text `i(nfo)` report directly in `$VISUAL`/`$EDITOR` |
| `m` (`m(eta)`) | All `i(nfo)` views | Open `<session>/meta.json` (`START SESSION`) or `<session>/<step>/meta.json` (step cards) in `$VISUAL`/`$EDITOR` |
| `Enter` | Copyable `i(nfo)` views | Copy the active bundle or step output to the clipboard and exit `i(nfo)` |
| `Esc` / `q` / `i` | All `i(nfo)` views | Exit cursor/part subview or return from `i(nfo)` to the inline prompt without scrollback clutter |

## Context Bundles & Part Inspection

- **Preamble headers & `Workdir` resolution**: Optional leading `Key: Value`
  lines on `stdin` (before the first blank line) are stored in
  `<session>/meta.json`. Non-transport preamble headers emitted via `export`
  (such as `Role`, `Task`, `Title`) appear in TUI headers and `<session>/0`
  by default, while `Bundle-*` transport headers (`Bundle-Name`,
  `Bundle-Command`, `Bundle-Protocol`, `Bundle-Boundary`) remain in
  `<session>/meta.json` only. When `RUN_BLOCK_CWD=auto`, an existing piped
  `Workdir` directory is preferred over the current directory or Git root.
- **Rule injection & deduplication**: `run` injects embedded `bash`
  execution rules into `===== Rules =====`, deduplicating against existing
  `run` / `blocks/bash` parts or `## Terminal blocks (` headings, and wraps
  unlabeled plain text under `===== Prompt =====`.
  `Sandbox: off` is omitted from `<session>/0` and clipboard output while
  remaining visible inside `i(nfo)`.
- **Boundary markers & hierarchical `Parts` table**: When
  `Bundle-Boundary: <nonce>` is present, `<!-- bundle:<nonce>:part {...} -->` /
  `<!-- bundle:<nonce>:end -->` markers are parsed into per-part metrics and
  stripped from `<session>/0` (keeping raw markers in `<session>/0.raw` for
  `e(dit)`, and falling back to `===== ... =====` sections when no boundary is
  set). The `Parts` table (`i(nfo)` and `--bundle-plan`) shows `%`,
  `CHARS`, `LINES`, `~TOK`, `KIND`, and `SOURCE` columns bracketed by top and
  bottom `100.0%` `[total]` rows, with sequential dim row numbers `1..M`,
  `chain`-indented `[bundle]` / `[rule]` tree shares, and automatic highlights
  for large parts (>=10% or ~3k tokens accented; >=25% or ~10k tokens warning).
- **Bundle protocol version & fragment kinds**: `Bundle-Protocol: 1` declares
  `context-bundle-protocol` v1; an unsupported version prints a warning on
  `stderr` while the bundle is still ingested. Fragments use the 4 canonical
  kinds `rule`, `file`, `cmd`, and `prompt`. Repeatable
  `-p`/`--prompt` text and interactive `p(rompt)` notes merge only into a
  trailing root user `prompt` fragment (`chain: []`, `name: "Prompt"`), or
  append a new trailing root `Prompt` part after upstream producer `prompt`
  fragments (such as `chain: ["vitalio/todo-md"]`), and any empty `prompt` fragment
  raises a `fragment_empty` warning in `--bundle-plan` and `START SESSION`.
- **Fragment deduplication & overlap warnings**: With a declared boundary,
  a fragment whose text (ignoring a leading `===== ... =====` header line and
  surrounding blank lines) is identical to an earlier fragment, or is a
  contiguous block of at least 3 lines inside one, is dropped from
  `<session>/0` (`0.raw` keeps it) and reported as a `fragment_deduped`
  warning naming the kept part and the saved lines/tokens. Upstream `prompt`
  fragments (with a non-empty `chain`) participate in deduplication, while the
  user's root session `prompt` fragment (`chain: []`) is never dropped. When
  two remaining fragments share a contiguous block of at least 5 lines and 200
  characters without being duplicates, a `fragment_overlap` warning shows the
  earlier part, shared line count, and overlap percentage in `--bundle-plan`
  and `START SESSION`.
- **Inspecting individual parts (`--bundle-plan` & `--show --part N`)**: Each
  part in `bundle_plan` records 1-based `line_start` / `line_end` offsets into
  cleaned `<session>/0`. Inspect the full table with `--bundle-plan` or slice a
  single 1-based part index `N` with `--show --part N` (`stdout` receives the
  part text; `stderr` receives a one-line summary):

```bash
run --bundle-plan s1
run --bundle-plan s1 --json
run --show s1 --part 1
run --show s1/0 --part 2
```

## Safety Scanner, Sandboxing & Approval Hooks

- **Pre-execution analysis (`--plan`)**: `run` parses Bash and Python
  scripts via AST and regex rules before running, expanding multi-file or
  read+write Python operations into sub-items and flagging destructive commands,
  network calls, credential access, or history mutations. Pipe any script to
  `run --plan` to emit the structured JSON execution and risk plan without
  running it.
- **Session sandboxing (`--sandbox` & `RUN_BLOCK_SANDBOX`)**: Restrict block
  execution with `off` (default), `strict` (read-only filesystem outside working
  / temp directories and restricted network where supported), `nonet` (network
  disabled), or a custom wrapper command prefix. Query or update a session's
  sandbox mode via `run --sandbox [MODE] [session]`; active non-`off`
  modes are recorded in `<session>/0`'s `Sandbox:` header.
- **External approval hook (`RUN_BLOCK_APPROVE_CMD`)**: When set, `run`
  pipes the `--plan` JSON to this validator command before execution: exit `0`
  approves automatically, exit `2` requires interactive user confirmation with
  the validator's note, and any other exit code rejects execution (`NOT RUN`).
- **Customizing risk rules (`RUN_BLOCK_SAFETY_*`)**: Disable specific built-in
  risk categories via `RUN_BLOCK_SAFETY_DISABLE=cat1,cat2` or register custom
  regex patterns via `RUN_BLOCK_SAFETY_RULES="cat1=regex1;cat2=regex2"`.

## Step Artifacts & `--fix` Diagnostics

- **Step descriptors & saved artifacts (`<session>/<step>/`)**: Child `stdout`
  and `stderr` share a single descriptor (the PTY slave or capture pipe write
  end), so `<session>/<step>/out` preserves the exact interleaved write order
  without a separate `stderr` file. `out` is written once the block finishes and
  ends with the `[<session>/<step>] END` marker. `aborted` marks a block that
  was declined or rejected before running, `error` records a pre-execution
  failure message shown by `--show`, and `meta.json` stores the structured
  outcome (`ok`, `failed`, `syntax-error`, `not-run`, `aborted`, `saved`), exit
  code, duration, optional `fix_target`, and model `reasoning` (also saved to
  `plan.md`).
- **Error summary & syntax context**: `END STEP` extracts its `Error:` summary
  line from the last meaningful line of `out` (preferring the last `Traceback`
  exception line when output ends with a generic test-runner summary tail). Both
  Python `SyntaxError` failures and shell syntax errors include a `+-2` line
  code context.
- **`--fix` failure hints & fuzzy-anchor repair**: When a `--fix` patch fails,
  `NOT RUN` appends `Hint:` lines diagnosing the root cause: closest matching
  line and similarity score for a missing anchor, trailing-newline mismatches,
  ambiguous anchors (`actual: N == 1`), discarded `text.replace(...)` /
  `re.sub(...)` return values, anchors located in a repository file instead of
  the target step script, or a shell script passed where a Python patch was
  expected (advising to run it as the next `<session>/<step>`). In an
  interactive TTY, a single missing anchor with `similarity >= 0.85` and a clear
  margin over the runner-up can be replaced on confirmation and re-run
  immediately; non-interactive `-y` / `--headless` runs never apply fuzzy
  matches. Pasted payloads stop at the first closing terminator, strip nested
  wrappers and fence debris, and recover a missing terminator before a closing
  fence.

## CLI Reference

### Commands

| Command | Description |
| :--- | :--- |
| `run [-p TEXT]` | Start a rule-only session on TTY `stdin` (or read context bundle from piped `stdin`), embedding optional repeatable `-p`/`--prompt` text |
| `<command> \| run [-p TEXT]` | Start a new session from `stdin` context bundle into `<session>/0`, appending optional `-p`/`--prompt` text |
| `run [-y] [--headless] <session>/<step>` | Run a block from `stdin` (`-y`/`--yes` auto-confirms `START STEP` and reopens a completed session while keeping TUI cards; `--headless` disables TUI boxes and prompts) |
| `run -r`, `--run [-c] [-y] [session]` | Ingest a full model reply from the system clipboard (`-c`/`--clipboard`, e.g. `run -rc`), `$VISUAL`/`$EDITOR` (on TTY `stdin`), or piped `stdin`, validate and repair the `RUN_BLOCK` / `RUN_FIX` block (or fenced code block when `[session]` is given) before allocating `<session>/<next_step>`, and display model reasoning in `START STEP` |
| `run --plan` | Analyze script from `stdin` and print JSON execution and safety plan |
| `run --bundle-plan [<session>] [--json]` | Print the `Parts (<N>):` table and diagnostics from `stdin` or an existing session |
| `run --fix [-y] <session>/<target>` | Patch `<target>` script via Python on `stdin` and run as `<target>_N` |
| `run --retry [-y] [session[/step]]` | Re-run a block, or the latest block of a session when only `<session>` is given (default: latest block overall) |
| `run --list`, `-l [session \| --filter TEXT]` | List sessions with block count, size, UTC timestamp, `Workdir`/`Role`/`Task` headers, the last step outcome (`ok (<duration>)`, `exit <rc> (<duration>)`, `syntax-error (exit <rc>)`, `not-run`, `aborted`, `saved`) and `next: <session>/<step>` for open sessions (`[DONE]` marks completed sessions without `next:`); `--filter TEXT` keeps only sessions whose name or any header value contains `TEXT` (case-insensitive) |
| `run --done [-y] [session] [-m NOTE]` | Mark a session (default: latest) as completed and print the `END SESSION` summary with accumulated statistics |
| `run --show [session[/step]] [--script \| --out]` | Show session path, state, size, update time, statistics, headers (including `Bundle-*` transport headers), and all blocks for a bare `<session>`, the `<session>/0` bundle, or saved script and output of `<session>/<step>`; `--script` / `--out` print only the script or only the captured output (a bare `<session>` selects its latest block) |
| `run --show [<session>[/0]] --part N` | Print only part `N` (1-based part `index` from `--bundle-plan --json`) of `<session>/0` (latest session when omitted); exits non-zero for non-zero steps or out-of-range parts |
| `run --sandbox [MODE] [session]` | Show or update session sandbox mode (`off`, `strict`, `nonet`) in `<session>/0` |
| `run --clean [opts] [session...]` | Prune sessions (`--keep N`, `--older-than DAYS`, `--max-size MB`, `--all`, or named sessions) |
| `run --start [-p TEXT] [--session NAME]` | Start session from `stdin` context bundle or rule-only on TTY into `<session>/0` |
| `run --config [KEY[=VALUE] \| --edit \| --path]` | Show effective settings with their sources, profiles, roles, and the active profile (secrets redacted); print one key, set it in `config.json` (`0600`; `KEY=` unsets; rejected inside a running block), open `config.json` in the configured editor (`--edit`), or print its path (`--path`) |
| `run --update [--check \| --force]` | Self-update `run` from GitHub (`vitalio/run-block`) or check for a newer version (`--check`) |
| `run --uninstall [--purge]` | Remove installed `run` / `run_block` binary (`--purge` also removes the state directory) |
| `run -V`, `--version` | Print version and exit `0` |
| `run -h`, `--help` | Print usage help and exit `0` |

### Options

| Option | Description |
| :--- | :--- |
| `-r`, `--run [session]` | Full-reply mode: extract block and reasoning from clipboard (`-c`), `$VISUAL`/`$EDITOR` (on TTY `stdin`), or piped `stdin` and infer `<session>/<next_step>` |
| `-c`, `--clipboard` | Read full model reply directly from the system clipboard (combine with `-r`/`--run`, e.g. `run -rc [session]`) |
| `-y`, `--yes` | Auto-confirm `START STEP` and reopen a completed session (keeps TUI cards and clipboard prompts) |
| `--headless` | Non-interactive headless mode without TUI boxes or prompts (same as `RUN_BLOCK_HEADLESS=1`) |
| `-p`, `--prompt TEXT` | Embed repeatable prompt text into the started session bundle (`===== Prompt =====`) |
| `-P`, `--profile NAME` | Model profile (or `<provider>:<model>`) for the started session; overrides role routing and `default_profile` and is saved in `<session>/meta.json` |
| `--sandbox [MODE]` | Set the sandbox mode for the run or started session (`off`, `strict`, `nonet`); bare flag means `strict` |
| `-V`, `--version` | Print version and exit `0` |
| `-h`, `--help` | Print usage help and exit `0` |

## Configuration Files & Model Profiles

Every setting resolves from the environment first, then the project
`.run-block.json`, then the user `config.json`, then the built-in default;
`run --config` prints each value with its source (`env`, `project`,
`config`, `default`).

- **User config**: `XDG_CONFIG_HOME/run-block/config.json` (default
  `~/.config/run-block/config.json`). An existing `models.json` in the same
  directory is used when `config.json` is absent, and `RUN_BLOCK_CONFIG=PATH`
  overrides both. Keys are the lowercase setting names (`pager`,
  `max_fix_attempts`, `approve_cmd`, ...) plus `default_profile`, `profiles`,
  and `roles`. `run --config KEY=VALUE` writes the file with `0600`
  permissions; an empty value unsets the key.
- **Project config**: `.run-block.json` in the working directory may set only
  non-privileged keys: `clipboard`, `token_stats`, `progress`, `pager`,
  `max_fix_attempts`, `max_state_mb`, `bundle_max_tokens`,
  `fragment_max_tokens`, `model`, `cache`, `compact_tokens`, `max_steps`,
  `default_profile`, and `roles`. Hooks, commands, safety switches, sandbox,
  paths, the update URL, and `profiles` (including `api_key_cmd`) are
  ignored and listed by `run --config`.
- **Invalid JSON** in either file fails with an explicit error.

```json
{
  "pager": "cat",
  "default_profile": "fast",
  "profiles": {
    "fast": {"provider": "openai", "model": "gpt-4.1-mini"},
    "deep": {"provider": "anthropic", "model": "claude-opus-4",
             "api_key_cmd": "pass show llm/anthropic", "cache": "system"}
  },
  "roles": {"plan": {"profile": "deep", "mode": "interactive", "max_steps": 40}}
}
```

Profile fields: `provider`, `model`, `base_url`, `api_key_env`,
`api_key_cmd`, `max_tokens`, `thinking`, `cache`. Role fields (roles `plan`,
`design`, `work`, `review`, `law`): `profile`, `mode`, `max_steps`.

The active profile is the first one found in this order: `-P`/`--profile
NAME`, `RUN_BLOCK_MODEL_<ROLE>`, `RUN_BLOCK_MODEL`, `roles.<role>.profile`
(role from the session `Role:` header), `model`, `default_profile`. A name
that is not a configured profile must be `<provider>:<model>` with provider
`anthropic`, `openai`, `gemini`, `openrouter`, or `deepseek`. The resolved
name is saved as `"profile"` in `<session>/meta.json` when a session starts.
Environment values of `RUN_BLOCK_CACHE` and `RUN_BLOCK_MAX_STEPS` override
the profile `cache` and role `max_steps` fields.

API keys are resolved only inside the `run` process (`api_key_env`,
`api_key_cmd`, the provider variable, then `RUN_BLOCK_API_KEY`). Provider key
variables (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`,
`OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY`, `RUN_BLOCK_API_KEY`, and every
profile `api_key_env`) are always removed from step environments, in every
sandbox mode.

## Environment Variables

`run` works out of the box without configuration files. Environment
variables override `.run-block.json` and `config.json` values:

| Environment Variable | Default | Description |
| :--- | :--- | :--- |
| `RUN_BLOCK_DIR` | `~/.local/state/run-block` | Session storage directory (`$XDG_STATE_HOME/run-block` on POSIX; automatically migrates legacy `~/.local/state/run_block`) |
| `RUN_BLOCK_CWD` | `auto` | `auto` (existing `Workdir` preamble header or session `Workdir` from `<session>/0`, nearest `.context.bundle`/`.agents_bundle`/`AGENTS.md` dir up to Git root, Git root, or `$PWD`), `cwd` (always `$PWD`), or explicit path |
| `RUN_BLOCK_CLIPBOARD` | `prompt` | `prompt` (interactive `[Y/n]` prompt), `auto` (copy automatically), `never` |
| `RUN_BLOCK_NO_CLIPBOARD` | `0` | Set to `1` to disable clipboard prompts and automatic copying (same as `RUN_BLOCK_CLIPBOARD=never`) |
| `RUN_BLOCK_HEADLESS` | `0` | Set to `1` (or pass `--headless`) for raw stdout protocol without TUI boxes or prompts |
| `RUN_BLOCK_SANDBOX` | `off` | Execution sandbox mode (`off`, `strict`, `nonet`, or custom wrapper prefix; active non-`off` modes are persisted in `<session>/0` `Sandbox:` header) |
| `RUN_BLOCK_APPROVE_CMD` | *(none)* | External/LLM validator command receiving `--plan` JSON on `stdin` (`0`=approve, `2`=prompt user with stdout note, other=reject) |
| `RUN_BLOCK_TOKEN_STATS` | `true` | Show char size and Claude/GPT/Gemini token counts (`true` / `false`) |
| `RUN_BLOCK_BUNDLE_MAX_TOKENS` | `100000` | Warn in `START SESSION` / `--bundle-plan` when total tokens exceed budget (`0` disables) |
| `RUN_BLOCK_FRAGMENT_MAX_TOKENS` | `20000` | Warn in `START SESSION` / `--bundle-plan` when a single fragment exceeds limit (`0` disables) |
| `RUN_BLOCK_PAGER` | `cat` | Non-interactive pager command exported to child steps across `PAGER`, `GIT_PAGER`, `GH_PAGER`, `MANPAGER`, `SYSTEMD_PAGER`, `BAT_PAGER`, `AWS_PAGER`, `PSQL_PAGER`, and `DELTA_PAGER` (`inherit`/`off`/`0`/`false` preserves parent pager variables) |
| `RUN_BLOCK_PROGRESS` | `1` | Show live `[N/M]` step progress markers and elapsed timings during interactive execution (`0`/`false` to disable) |
| `RUN_BLOCK_MAX_FIX_ATTEMPTS` | `2` | Max consecutive failed `--fix` attempts per base step before requiring `<session>/<step+1>` |
| `RUN_BLOCK_MAX_STATE_MB` | `100` | Warn on `stderr` when total session state size exceeds this threshold in MB (`0` disables) |
| `RUN_BLOCK_SHELL` | `bash` | Shell binary (`bash` or POSIX `sh`) |
| `RUN_BLOCK_EDITOR` | `auto` | Override editor command for `e(dit)`/`s(cript)`/`o(utput)`/`v(iew)` inside `i(nfo)` (`auto` uses `VISUAL` / `EDITOR`) |
| `VISUAL` / `EDITOR` | `vim`/`less`/`nano` | Terminal editor/viewer for `e(dit)`/`s(cript)`/`o(utput)`/`v(iew)` inside `i(nfo)` |
| `RUN_BLOCK_SAFETY_DISABLE` | *(none)* | Comma-separated built-in risk categories to disable |
| `RUN_BLOCK_SAFETY_RULES` | *(none)* | Semicolon-separated `<cat>=<regex>` rules |
| `RUN_BLOCK_UPDATE_URL` | GitHub `main/run` | Override remote script URL used by `--update [--check]` |
| `RUN_BLOCK_CONFIG` | `XDG_CONFIG_HOME/run-block/config.json` | User config file path (falls back to an existing `models.json`) |
| `RUN_BLOCK_MODEL` | *(none)* | Model profile name (or `<provider>:<model>`) for all sessions |
| `RUN_BLOCK_MODEL_<ROLE>` | *(none)* | Model profile for one role (`PLAN`, `DESIGN`, `WORK`, `REVIEW`, `LAW`) |
| `RUN_BLOCK_CACHE` | `auto` | Prompt cache breakpoint mode for API sessions (`auto`, `system`, `off`) |
| `RUN_BLOCK_COMPACT_TOKENS` | `120000` | Input token threshold for API history compaction |
| `RUN_BLOCK_MAX_STEPS` | *(none)* | Step limit for API autopilot sessions |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY`, `RUN_BLOCK_API_KEY` | *(none)* | Provider API keys, read only by `run` and never exported to steps |

### Variables Exported to Step Processes

Every block runs with these variables in its environment:

| Environment Variable | Description |
| :--- | :--- |
| `IN_RUN_BLOCK` | Always `1` inside a running step |
| `RUN_BLOCK_PARENT_SESSION` / `RUN_BLOCK_PARENT_STEP` | Session name and step directory of the running block |
| `PAGER`, `GIT_PAGER`, `GH_PAGER`, `MANPAGER`, `SYSTEMD_PAGER`, `BAT_PAGER`, `AWS_PAGER`, `PSQL_PAGER`, `DELTA_PAGER` | Set to `RUN_BLOCK_PAGER` (default `cat`) unless disabled via `RUN_BLOCK_PAGER=inherit\|off\|0\|false` |

## License

[MIT](LICENSE) © 2026 [vitalio](https://github.com/vitalio)

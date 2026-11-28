# `run-block` (`run`) — Project-Specific Agent Rules

Universal workflow, language, Git, SemVer, Python CLI, and single-file build
rules are loaded via `.context.bundle`.

## Architecture & Module Boundaries

- `src/header.py` — `--help` row tables (`HELP_*`), standard library imports,
  version constants, and the embedded rule placeholders
  (`EMBEDDED_RULE_BASH`, `EMBEDDED_RULE_API`) populated by `build.py`.
- `src/config.py` — settings
  resolution (`_SETTING_SPECS`, `get_setting()` returning `(value, source)`
  with precedence env, project `.run-block.json`, user `config.json`, default),
  config file loading and `0600` writes (`config_file_path()`,
  `set_config_value()`), model profile and role resolution
  (`resolve_profile()`), parent-only API key resolution (`resolve_api_key()`),
  provider key names for child scrubbing (`provider_secret_env_names()`),
  non-interactive child pager variable tuple (`CHILD_PAGER_ENV_VARS`
  controlled by `RUN_BLOCK_PAGER`, default `cat`), and `usage_text()`, which
  renders `--help` from the `HELP_*` tables (thematic command sections, unified
  description column across all sections, lines <= 100 display columns).
- `src/session_meta.py` — session/step metadata persistence
  (`<session>/meta.json`, `<session>/<step>/meta.json`), session lifecycle
  state (`get_session_state()`), bundle header parsing, `Workdir`/`Sandbox`
  resolution, and `IN_RUN_BLOCK=1` deferred `end_session` card state.
- Config invariants: add every new setting only to `_SETTING_SPECS`; project
  `.run-block.json` is filtered through `PROJECT_CONFIG_ALLOWLIST` and never
  supplies hooks, commands, safety switches, sandbox, paths, `update_url`, or
  `profiles`; `profiles` come only from the user config; `--config` mutations
  exit `2` inside a running block; `scrub_child_env()` (`src/safety.py`)
  strips provider API key variables in every sandbox mode; the resolved
  profile name is persisted as `"profile"` in `<session>/meta.json`
  (`_SESSION_STATE_KEYS`).
- `agents/run.md` and `agents/run-api.md` — internal embedded terminal
  execution rule sources (`EMBEDDED_RULE_BASH` for text/clipboard mode and
  `EMBEDDED_RULE_API` for built-in API tool-call mode) injected by `build.py`
  into `src/header.py`. Update both rule files in the same commit whenever
  step numbering, `--fix` constraints, or session rules change.
- `src/safety.py` — AST/regex operation classifier, safety risk scanner,
  `run --plan` JSON output, and `RUN_BLOCK_APPROVE_CMD` validator hook.
- `src/ui.py` — terminal/ANSI/UTF-8 and display-width primitives, token
  counting and stats formatting (`count_tokens()`, `format_stats()`), and thin
  open-right box-drawing (`╭─ TITLE ───`, `│ `, `╰───`, ASCII fallback) TUI card
  layout and rendering (`START STEP`, `START SESSION`, `END STEP`, `NOT RUN`,
  `SYNTAX ERROR`) capped at `min(term_cols, 100)` display columns (`MAX_CARD_COLS = 100`).
  `START STEP` and `END STEP` cards follow a symmetric layout: minimal unspaced
  step headers (`Step`, `Workdir`, non-`off` `Sandbox`, plus `Exit`/`Error`/`Fix`
  on failure), a phase-level `Stats:` line (`Reasoning + Script` on `START STEP`;
  `Output + Prompt` plus duration on `END STEP`), and per-section `<Section> (<stats>):`
  previews (`Reasoning` + single-line `…`-truncated `Script` operations on
  `START STEP`; `Output` preview lines + optional user `Prompt` on `END STEP`).
- `src/ui_info.py` — fullscreen `i(nfo)` inspector (using full `term_cols`),
  horizontal-rule-separated section layout (`Headers`, `Reasoning`, `Script`,
  `Output`, `Prompt`) with an overview mode capping each section to ~1/3
  terminal height, two-column vertical split (`Session Headers │ Step Headers`)
  in the `Headers` section, `Tab` section cycling, `Enter` or direct hotkeys
  (`h`, `r`, `s`, `o`, `p`) to expand a section to fullscreen, `e(dit)` to open
  `$EDITOR` from fullscreen, and in-TUI session history navigation (`b` for
  `<session>/0` bundle plan, `[`/`]` or `Left`/`Right` for prev/next step,
  `{`/`}` or `Home`/`End` for session start `<session>/0` / latest step) treating
  each step `sN/k` as a single navigation node with pre-execution (`parent = k-1`)
  and post-execution (`parent = k`) branching points.
- `src/ui_prompt.py` — `/dev/tty` lifecycle, `SIGWINCH` debounce watcher,
  editor launch and `.orig` backups, `$EDITOR`-backed step prompt creation and
  re-editing (`<step>/prompt.md` via `p(rompt)`), clipboard command resolution,
  copying, and reading (`clipboard_command()`, `clipboard_read_command()`,
  `read_clipboard_text()`), and interactive confirmation and clipboard prompts
  (`confirm_execution()` with `-> Execute this block? [Y/n] · i(nfo) h(eaders) r(easoning) s(cript):`
  and inline `a(ppend)` / `o(verwrite)` conflict resolution when a step number
  already exists or skips a previous step, `prompt_yes_no_box()`,
  `offer_clipboard_copy()`).
- `src/runner.py` (and `src/reply.py`, `src/fix.py`, `src/inspect_cmd.py` split
  in `F93`) — sequential session/step execution (`<session>/<step>`,
  `run_script()`, `cmd_normal()`, `cmd_retry()`), `-y`/`--yes` auto-confirm mode,
  and `--headless` (`RUN_BLOCK_HEADLESS=1`) headless mode in `src/runner.py`;
  `-r`/`--run [-c|--clipboard] [session]` (`run -rc`) full-reply ingestion with
  pre-allocation reply validation (`extract_reply_block()`,
  `normalize_api_tool_script()`, `format_protocol_reminder_lines()`,
  `cmd_run_reply()`), glued `RUN_BLOCK`/`RUN_FIX`/fence recovery, transport-mode
  protocol reminders (`reply_transport: "text" | "api_tool"`), and output
  prompt-injection / delimiter-spoofing warnings in `src/reply.py`;
  `--fix` Python AST anchor diagnosis and patching (`cmd_fix()`) in `src/fix.py`;
  and session/step inspection and lifecycle commands (`--list`, `--show`,
  `--clean`, `--sandbox`, `--done`) in `src/inspect_cmd.py`. Child `stdout` and `stderr` share one descriptor (the PTY
  slave or the capture pipe write end), so `out` keeps exact write order and
  the `END STEP` box takes its `Error:` line from the last meaningful line of
  `out`; there is no separate `err` artifact. Exports non-interactive
  pager defaults (`CHILD_PAGER_ENV_VARS` set to `get_setting("pager")[0]`,
  default `cat`, unless disabled via `RUN_BLOCK_PAGER=inherit|off|0|false`) in
  the child execution environment while keeping PTY `stdin` connected for
  intentional interactive prompts.
- `src/bundle_parse.py` — Bundle Input Protocol header constants and filtering,
  embedded terminal block rule and prompt injection, section metadata
  inference, fragment deduplication/overlap detection, and
  `analyze_bundle_warnings()` diagnostics (pure parsing and analysis, no
  session I/O or rendering).
- `src/bundle_plan.py` — `bundle_plan` data model and provenance chain helpers,
  line range assignment and `--part N` extraction, plan construction and header
  reconciliation (`parse_bundle_fragments()`, `reconcile_bundle_plan()`), and
  `<session>/meta.json` persistence (`refresh_bundle_plan_meta()`,
  `load_session_bundle_plan()`).
- `src/bundle_view.py` — provenance tree construction, heavy-row classification,
  hierarchical table rendering, summary/parts/warning item formatters, and
  `--bundle-plan` text/CLI output (`cmd_bundle_plan()`).
- `src/agent.py` — Bundle-Protocol v1 cache-prefix splitter
  (`split_bundle_for_api()`, `classify_bundle_parts_for_api()`), single `run`
  tool schema and multi-call guard (`build_run_tool_schema()`,
  `normalize_run_tool_call()`, `process_assistant_tool_calls()`), stdlib
  `urllib.request` streaming SSE clients for Anthropic Messages
  (`/v1/messages` with `cache_control` ephemeral breakpoints under
  `RUN_BLOCK_CACHE=auto|system|off`) and OpenAI-compatible Chat Completions
  (`/v1/chat/completions` with `stream_options: {"include_usage": true}`),
  and `<session>/chat.json` transcript, threshold compaction
  (`RUN_BLOCK_COMPACT_TOKENS`), and provider usage persistence.
- `src/bundle.py` — session initialization from TTY `stdin` (rule-only) or
  piped `stdin` (`run` / `<command> | run` -> `<session>/0` and
  `<session>/meta.json`), injecting embedded `bash` terminal block rules via
  `format_start_bundle()`. Parses
  optional leading `Key: Value` header lines (separated from the body by a
  blank line) into `<session>/meta.json`, keeping `<session>/0` limited to
  `run`'s own headers (`Session`, `Next-Block`, `Workdir`, `Sandbox`,
  `Date`) and the prompt body.
- Session completion state (`--done`) and nested `IN_RUN_BLOCK=1` contract:
  persist `"completed": true` and `"completed_at"` (UTC ISO timestamp),
  optional `"completed_note"`, and accumulated `"stats"` (updated by
  `run_script` via `update_session_stats`) in `<session>/meta.json` without
  altering `<session>/0` headers. `run_script` exports `IN_RUN_BLOCK=1`,
  `RUN_BLOCK_PARENT_SESSION`, and `RUN_BLOCK_PARENT_STEP`; inside a running
  step, nested step execution (`<session>/<step>`, `--fix`, `--retry`),
  session initialization (`--start` or piped bundle initialization — worker
  sessions are started by external orchestration outside `IN_RUN_BLOCK=1`),
  `--config` mutations, and `--sandbox` mutations exit `2`, while `--done`
  logs a single plain line to `stdout` and queues an `end_session` event in
  `<parent_sdir>/<parent_step>/deferred.json` so `run_script` renders
  `END STEP` -> `END SESSION` in order after updating step stats. Before
  running any block (`<session>/<step>`, `--fix`, or `--retry`) on a completed
  session, warn and prompt for confirmation (`SESSION COMPLETED`, default
  `No`), clearing the completed flag only when confirmed (or when `-y`/`--yes`
  is explicitly passed).
- Session lifecycle states and step outcome labels (`src/session_meta.py`,
  `src/runner.py`):
  - Session lifecycle state (`get_session_state(sdir)`): `done` when
    `<session>/meta.json` has `"completed": true`; `active` when not completed
    and at least one step directory (`_iter_session_steps(sdir)`) exists;
    `bundle-only` when `<session>/0` exists without step directories (or
    `empty` when neither exists).
  - Step execution outcomes (`write_step_meta`, `_step_outcome`,
    `_step_status`): persist structured `"outcome"` (`"ok"`, `"failed"`,
    `"syntax-error"`, `"not-run"`, `"aborted"`, `"saved"`), `"exit_code"`,
    `"duration_ms"`, optional `"reason"`, `"fix_target"`, and model
    `"reasoning"` (also written to `<step>/plan.md`) in
    `<session>/<step>/meta.json` across all exit paths (falling back to
    `aborted`/`out`/`error`/`block.*` artifacts for legacy step directories).
    Keep `[<session>/<step>] END (...)` exclusively as the agent stream marker
    inside `<step>/out`, while rendering human/CLI step status labels as
    `ok (<duration>)`, `exit <rc> (<duration>)`, `syntax-error (exit <rc>)`,
    `not-run`, `aborted`, or `saved`.
  - `_iter_session_steps(sdir)` enumerates all step directories (`\d+(?:_\d+)?`)
    containing script, fix, output, error, abort, or metadata artifacts sorted
    by `_step_sort_key` (including `not-run` `--fix` attempts that failed before
    emitting `block.sh`), while `_iter_session_scripts(sdir)` returns runnable
    script paths.
  - Step artifacts in `<session>/<step>/`: `out` holds the START line, optional
    headers, child output in exact write order (`stdout` and `stderr` share one
    descriptor), diagnostics, and the END line, written once after the child
    exits; `error` holds a pre-execution failure message shown by `--show`;
    `aborted` marks a declined or rejected block and is removed when the block
    runs; `meta.json` records the structured outcome. Legacy `err` files are
    ignored.
  - `run -l` / `--list [session]` displays session lifecycle state,
    `last: <ref> (<step_status>)`, and `next: <session>/<next_free_step>` for
    open sessions (`active` / `bundle-only`) or `[DONE]` without `next:` for
    completed sessions.
- `src/cli.py` — CLI argument routing without hidden legacy flag aliases
  (`--show [session[/step]] [--part N | --script | --out]` unifies session
  overview, bundle/part, and step inspection without a separate `--info` flag
  or `--bundle-plan --part N`; `-c` is exclusively `--clipboard`, while API
  session continuation uses explicit `--continue`; `--sandbox off` replaces
  `--no-sandbox`), `--config` (`cmd_config()`), `-P`/`--profile` extraction
  (session start only), self-update (`--update [--check | --force]`), and
  `--uninstall [--purge]`.
- `tests/helpers.py` — shared `ROOT`, `SCRIPT`, `INSTALL_SH`, cached
  `load_module()`, and `RunBlockTestCase` with in-process CLI helpers (`_run`,
  `_run_in_process`, `_run_subprocess`, `_assert_ok`) and `RUN_BLOCK_*`
  environment isolation.
- `tests/test_cli.py`, `tests/test_safety.py`, `tests/test_ui.py`,
  `tests/test_bundle.py`, `tests/test_runner.py`, `tests/test_agent.py` —
  modular offline unit test suites mirroring `src/` boundaries.

## Bundle Input Protocol

- Header contract: Treat `Bundle-*` preamble headers (`Bundle-Name`,
  `Bundle-Command`, `Bundle-Protocol`, `Bundle-Boundary`) as transport metadata
  for `<session>/meta.json` only, never forwarding them into `<session>/0`.
  Forward all non-transport, non-hidden `stdin` preamble headers into
  `<session>/0` by default (never overriding `Session`, `Next-Block`, `Workdir`,
  `Sandbox`, or `Date`).
- Fragment parsing & stripping: When `Bundle-Boundary: <nonce>` is present,
  parse `<!-- bundle:<nonce>:part {...} -->` / `<!-- bundle:<nonce>:end -->`
  markers (agnostic of generator internals via `kind`, `group`, `name`, `via`,
  `rc`, `ms`), compute per-part line/byte/token counts, strip all markers from
  `<session>/0`, and persist structured `bundle_plan` metadata in
  `<session>/meta.json`. Fall back to `===== ... =====` section splitting when
  no boundary is declared.
- Protocol version and fragment kinds: `get_bundle_protocol()` reads
  `Bundle-Protocol`; `format_start_bundle()` warns on `stderr` for versions
  outside `SUPPORTED_BUNDLE_PROTOCOLS` without rejecting the bundle.
  `normalize_fragment_kind()` lowercases and strips fragment kind tokens for
  the 4 canonical `CANONICAL_FRAGMENT_KINDS` (`rule`, `file`, `cmd`, `prompt`,
  defaulting empty kinds to `part`). Upstream prompt
  fragments carry a non-empty `chain` (and can be deduplicated by
  `_dedupe_fragments()`), whereas the user's root session prompt fragment has
  `chain: []` (`name: "Prompt"`): `inject_embedded_prompt()`,
  `append_note_to_raw_bundle()`, and `refresh_bundle_plan_after_edit()` merge
  only into a trailing root user prompt fragment (`chain: []`) and otherwise
  append a new root `Prompt` part, and `analyze_bundle_warnings()` flags any
  empty prompt fragment (`fragment_empty`).
- Part line ranges: each part entry records 1-based `line_start` / `line_end`
  into the cleaned `<session>/0` (body-relative for `stdin`; `line_offset`
  tracks the header shift applied by `reconcile_bundle_plan`, which keeps the
  shift idempotent). Never store fragment text in `meta.json`; `--part N`
  slices `<session>/0` using these ranges (`extract_bundle_part`).
- Analyzer & diagnostics: Keep parsing and size/error/secret diagnostics in
  `src/bundle_parse.py`, plan state and persistence in `src/bundle_plan.py`,
  and `--bundle-plan` rendering in `src/bundle_view.py`, reusing
  `src/safety.py` secret detection without duplicating patterns.
- Fragment dedup and overlap: `parse_bundle_fragments()` drops duplicate or
  contained boundary fragments via `_dedupe_fragments()` before ranges are
  assigned, so `<session>/0`, `bundle_plan` ranges, and `0.raw` re-parsing
  stay consistent; `fragment_deduped` warnings carry pre-header part indices
  and `reconcile_bundle_plan()` shifts both `part_index` and `overlap_with`.
  `analyze_bundle_warnings()` emits `fragment_overlap` through
  `_detect_fragment_overlaps()` using `OVERLAP_MIN_LINES` / `OVERLAP_MIN_CHARS`.

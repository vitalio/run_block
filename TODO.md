# 🎯 [NEXT] B20: Fix buffered SSE streaming, OpenAI cached prompt token double-counting, and AI gateway/Vertex endpoint & header support

- Depends on: F102
- Bump: `PATCH`
- Fix `F102` review findings and cloud/enterprise AI gateway compatibility in `src/agent.py` and `src/config.py`:
  - **Incremental SSE streaming (`iter_sse_events`, `_open_sse_request`, `stream_anthropic_messages`, `stream_openai_chat`):** Yield `(event_name, data_str)` tuples incrementally as lines arrive from the HTTP response stream inside the `with` context instead of buffering the entire response into a `list` before returning from `_open_sse_request()`, so `on_text` callbacks fire live during streaming.
  - **Accurate total input context tokens across Anthropic and OpenAI-compatible providers (`normalize_usage_dict`, `_accumulate_usage`, `_reported_prompt_tokens`, `append_assistant_turn`):** Account for provider semantics where Anthropic `input_tokens` excludes `cache_read_input_tokens + cache_creation_input_tokens` whereas OpenAI-compatible `prompt_tokens` already includes `cached_tokens` (copied to `cache_read_input_tokens`), avoiding double-counting cached tokens when checking `RUN_BLOCK_COMPACT_TOKENS` and recording `last_input_tokens`.
  - **Cloud & enterprise AI gateway compatibility (`resolve_provider_endpoint`, profile `headers` / `auth_header`):** Recognize `/openapi` (e.g. GCP Vertex AI `.../endpoints/openapi`) alongside `/v1` and `/openai` in `resolve_provider_endpoint()` so it appends `/chat/completions` rather than `/v1/chat/completions`, and support optional profile `headers` (dict of custom HTTP headers) and `auth_header` (`"bearer"` or `"x-api-key"`) so Anthropic/OpenAI enterprise gateways (such as `claude-appgw`, LiteLLM, Cloudflare, Portkey, or Vertex proxies) can authenticate with either `x-api-key` or `Authorization: Bearer`.
- Add unit tests in `tests/test_agent.py` verifying incremental `on_text` emission before stream completion, OpenAI vs Anthropic compaction threshold token accounting, `/endpoints/openapi` URL resolution, and custom gateway headers.

# 🎯 [NEXT] F110: Remove legacy run_block, .agents_bundle, and models.json migration shims

- Depends on: F108
- Bump: `PATCH`
- Remove post-ADR-0004 legacy migration shims and fallbacks across `src/`, `install.sh`, `README.md`, and `tests/` (retaining canonical `RUN_BLOCK_*` / `IN_RUN_BLOCK` environment variables and `in_run_block()` / `parent_run_block_ref()` helpers):
  - `src/header.py`, `src/cli.py`, & `install.sh`: remove `LEGACY_REPO_MARKER = "run_block-repo: vitalio/run_block"`, `REPO_MARKERS`, `_cleanup_legacy_binary_and_state()`, `dest.name == "run_block"` redirection in `cmd_update()`, and `run_block` binary / state directory cleanup in `cmd_uninstall()` and `install.sh` (change conflict fallback `ALT_NAME="run_block"` to `ALT_NAME="run_cli"` in `install.sh`).
  - `src/config.py`: remove `_migrate_state_dir()` (`~/.local/state/run_block` -> `~/.local/state/run-block` rename/symlink migration), remove `LEGACY_CONFIG_FILE_NAME = "models.json"` fallback in `config_file_path()` (and `HELP_ENV`), and drop `".agents_bundle"` from `PROJECT_ROOT_MARKERS = (".context.bundle", "AGENTS.md")`.
  - `src/bundle_parse.py`, `src/agent.py`, & `src/runner.py`: drop `.replace("{cmd:run_block}", prog)` in `src/bundle_parse.py` and `src/agent.py` (`get_embedded_api_rule()`), drop `".agents_bundle"` from `_ROOT_AGENTS_MD_CHAINS` in `src/agent.py`, and drop `blocks/bash` from `EMBEDDED_RULE_ID_RE` in `src/bundle_parse.py`; drop `(?:_block)?` from `SPLIT_HEADER_RE`, `REPLY_CMD_HEADER_RE`, and `PROSE_BULLET_HDR_RE` in `src/runner.py` (or `src/reply.py` if after `F93`) so block fences match canonical `run`.
  - `README.md` & `tests/`: remove references to `.agents_bundle`, `models.json`, `run_block` binary, and `~/.local/state/run_block` migration from `README.md`; remove legacy migration tests in `tests/test_cli.py` and update legacy `agents_bundle`, `todo_md`, `vitalio/run_block:blocks/bash`, and `run_block s1/1` test fixtures across `tests/test_*.py`.
- Rebuild `./run` via `python3 build.py` and verify the full test suite passes.

# 🎯 [NEXT] F106: Add model-order (system/user) view mode and interactive toggle to --bundle-plan and START SESSION info

- Depends on: F102, F108
- Bump: `MINOR`
- Add an explicit model-delivery order view mode alongside the existing source-chain tree in `src/bundle_view.py`, `src/ui_info.py`, `src/header.py`, and `README.md`:
  - Support `--order` (and `--tree`, default `--tree`) on `run --bundle-plan [<session>] [--order | --tree] [--json]`.
  - In `order` mode, render bundle parts strictly in their stitched prompt delivery order grouped under the two API message containers defined in `docs/adr/0001-built-in-api-agent-mode.md`: `[system]` (all `kind == "rule"` parts in exact `===== Rules =====` order plus root `AGENTS.md` `kind == "file"`) and `[user]` (`kind == "header"` session preamble followed by `cmd`, remaining `file`, and `prompt` parts in exact `line_start..line_end` order), displaying each part's canonical part index.
  - In the interactive `START SESSION` `i(nfo)` fullscreen viewer (`src/ui_info.py`), bind hotkey `o` (`o(rder): model/tree` in the footer bar) to toggle live between the source-chain tree and the model-delivery order table while keeping `Tab: parts` and `Enter: open part` navigation working seamlessly in both modes.
- Add unit tests in `tests/test_bundle.py` and `tests/test_ui.py` covering `--bundle-plan --order`, `[system]`/`[user]` grouping metrics, and interactive `o` mode toggling in `START SESSION` info.

# 🎯 [NEXT] F109: Redesign START/END STEP cards, multi-section fullscreen info, editor prompts, and in-TUI history navigation

- Depends on: F93
- Bump: `MINOR`
- Redesign `START STEP` / `END STEP` TUI cards, step conflict resolution, fullscreen `i(nfo)` section layout, `$EDITOR`-backed step prompts, and in-TUI session history navigation in `src/ui.py`, `src/ui_info.py`, `src/ui_prompt.py`, and `src/runner.py` per `D11`:
  - Cap normal-mode TUI cards (`START SESSION`, `START STEP`, `END STEP`, `END SESSION`, `CLEAN SESSIONS`, `SESSION COMPLETED`) at `min(term_cols, 100)` display columns (`MAX_CARD_COLS = 100`) with minimal unspaced headers (`Step`, `Workdir`, non-`off` `Sandbox`, plus `Exit`/`Error`/`Fix` on failure), a phase-level `Stats:` line (`Reasoning + Script` on `START STEP`; `Output + Prompt` plus duration on `END STEP`), and per-section `<Section> (<stats>):` previews (`Reasoning` preview lines + single-line `…`-truncated `Script` operation rows on `START STEP`; `Output` preview lines + optional user `Prompt` preview lines on `END STEP`).
  - Simplify the `START STEP` prompt to `-> Execute this block? [Y/n] · i(nfo) h(eaders) r(easoning) s(cript):` (dropping top-level `e(dit)` so `e` opens `$EDITOR` inside fullscreen view) and fold step-number conflicts directly into `START STEP` using `a(ppend)` (renumber to the latest free step at the end of the session) and `o(verwrite)` (replace the existing step in place) instead of separate `STEP ALREADY EXISTS` / `MISSING PREVIOUS STEP` cards.
  - Replace single-line `readline()` prompt appending on `END STEP` with `$EDITOR`-backed editing of `<session>/<step>/prompt.md` via `p(rompt)`: pressing `p` when no prompt exists opens `$EDITOR` and renders the saved `Prompt (<stats>):` section on the card; pressing `p` again reopens `$EDITOR` to edit the existing prompt and refreshes the card (and copies `<step>/out` + `<step>/prompt.md` together).
  - Structure fullscreen `i(nfo)` (using full `term_cols`) into horizontal-rule-separated sections (`Headers`, `Reasoning`, `Script`, `Output`, `Prompt`): render `Headers` as a two-column vertical split (`Session Headers │ Step Headers`), cap each section in overview mode to ~1/3 terminal height with single-line operation rows, bind `Tab` to cycle sections, and bind `Enter` or direct hotkeys (`h`, `r`, `s`, `o`, `p`) to expand a section to fullscreen (`e(dit)` opens `$EDITOR`).
  - Add in-TUI session history navigation across cards and `i(nfo)`: `b(undle)` to inspect `<session>/0`, `[`/`]` (`Left`/`Right`) to step backward/forward through `<session>/0 .. <session>/<latest>`, and `{`/`}` (`Home`/`End`) to jump to the start (`<session>/0`) or latest step of the session.
- Add unit tests in `tests/test_ui.py` and `tests/test_runner.py` covering the 100-column card cap, symmetric `START STEP` / `END STEP` `Stats:` and section previews, inline `a(ppend)` / `o(verwrite)` conflict handling, `$EDITOR` prompt creation/re-editing, two-column `Headers` split, multi-section `i(nfo)` overview/fullscreen transitions, and `[`/`]`/`{`/`}`/`b` history navigation.

# 🎯 [NEXT] D4: Design workspace state fingerprinting and drift detection across steps

- Depends on: F92, F93
- Explore computing a lightweight workspace state fingerprint (`state_before` / `state_after`, e.g. Git `HEAD` + status/diff digest or non-Git directory metadata hash) around step execution in `src/runner.py`.
- Define how state drift between consecutive steps (manual edits or external processes modifying files after the previous step's `state_after`) is detected, surfaced in `src/ui.py` (`START STEP` / `END STEP`), and classified as mutating vs read-only in `src/safety.py` and `tests/test_runner.py` and `tests/test_safety.py`.

# 🎯 [NEXT] D6: Design session execution policies and post-step revert guards

- Depends on: D4
- Evaluate declarative session-level execution constraints, granular per-step sandbox permissions, and network domain allowlisting in `meta.json` / `context-bundle-protocol` preamble headers (`src/bundle.py`, `src/config.py`, `src/runner.py`, `src/safety.py`, `src/ui.py`):
  - Role & path write policies: support role-based allowed write globs (e.g. `role=plan` restricted to `TODO*.md`, `role=design` restricted to `docs/adr/**`, `AGENTS.md`, and `TODO*.md`, `role=review` read-only), hard blocks on destructive patterns (`rm -rf /`, `rm -rf ~`, outside-`Workdir` deletes, `.git/hooks` or `~/.ssh` tampering), and pre-step working-tree snapshots (`git stash create`) with one-key `r(evert)` in `END STEP` (or automatic rollback on policy violation).
  - Declarative workspace directories & granular per-step sandbox permissions in `START STEP`: keep `run-block` completely decoupled from `todo-md` file formats (never parse `.todo_projects` or hardcode `todo -C` inside `run-block`); instead, receive allowed sibling workspace directories and path write policies declaratively via `context-bundle-protocol` session headers / `meta.json` (supplied by upstream producers, `.context.bundle`, or `lets`). Default to `nonet` / `strict` OS-level isolation (`bwrap` / `sandbox-exec`, hiding `~` and `~/.ssh` so even obfuscated Python/Node commands triggered by a prompt injection cannot exfiltrate secrets or access the network at the syscall level), mount declared workspace directories according to session write policy (read-only by default, or scoped write access such as child `TODO*.md` in orchestrator sessions), detect when a step requires network access (`git push`/`pull`, `curl`) or extra directory mounts in `src/safety.py`, and let the user grant one-step network or extra-folder access interactively in `START STEP` via `s(andbox)` without disabling isolation for the rest of the session.
  - Network domain allowlist proxy (`allowed_domains`): design a lightweight stdlib-only localhost HTTP `CONNECT` / SOCKS proxy inside the parent `run` process bridged into the `nonet` / `strict` sandbox so steps can be restricted to explicit trusted domains (e.g. `github.com`, `api.github.com`, `pypi.org`) while blocking all direct outbound sockets, arbitrary domains, and DNS exfiltration.
- Cover enforcement, declarative workspace directory mounts, per-step permission prompts, domain proxy filtering, and rollback semantics in `tests/test_runner.py`, `tests/test_safety.py`, and `tests/test_ui.py`.

# 🎯 [NEXT] D7: Design pre-flight sandbox dry-run preview via temporary git worktree

- Depends on: D6
- Explore an optional pre-flight simulation mode (`src/config.py`, `src/runner.py`) that executes a candidate block inside a temporary lightweight `git worktree` (or isolated copy) before touching the main working tree.
- Define how actual mutated files and diff summaries are presented in `START STEP` (`src/ui.py`, `src/safety.py`), how cleanup and non-Git fallbacks behave, and how to test safely in `tests/test_runner.py` and `tests/test_safety.py`.

# 🎯 [NEXT] D5: Design tamper-evident hash chain and parent-step verification for session history

- Depends on: D4
- Evaluate storing a SHA-256 digest per executed step (covering script text, exit code, output, and post-step state fingerprint) linked via `prev_hash` in `src/runner.py`.
- Clarify protocol details for optional parent-hash anchoring in `Next-Block` headers (`agents/run.md`), a `run --verify <session>` integrity check in `src/cli.py`, and test coverage in `tests/test_runner.py` and `tests/test_cli.py`.

# 🎯 [NEXT] D8: Design explicit parent-step DAG lineage for session branches and retries

- Depends on: D5, F109
- Explore recording explicit `parent_step` / `parent_hash` metadata for every step, `--fix` patch (`s1/1_1`), and `--retry` run in `src/runner.py` so session history forms an unambiguous DAG rather than relying solely on lexical step names.
- Align the parent-step DAG and time-travel model with the unified step node and five-section TUI structure (`Headers`, `Reasoning`, `Script`, `Output`, `Prompt`) from `D11`:
  - Treat each step `sN/k` as a single navigation node for `[`/`]` (`Left`/`Right`) and `{`/`}` (`Home`/`End`), while supporting two distinct branching points: pre-execution branching from `parent_step = k - 1` (re-generating, editing, or patching a proposed `Reasoning` + `Script` reply against the post-`k-1` workspace state) and post-execution branching from `parent_step = k` (forking from a completed step `k`'s `Output` by editing/adding a user `Prompt` via `p(rompt)` in `$EDITOR` or reverting the workspace snapshot).
  - Define how branch lineage is inspected in `--list` / `--show` and navigated via `[`/`]` in the TUI, and how it is verified in `tests/test_runner.py` and `tests/test_cli.py`.

# 🎯 [NEXT] F103: Add proposed step state machine, safe autopilot, and supervisor-session CLI (run --step)

- Depends on: F93
- Depends on: F101 -> F102 -> B20
- Depends on: L1 -> F104
- Depends on: B17
- Bump: `MINOR`
- Implement the step proposal state machine (`outcome: "proposed"`), strict `awaiting_reply` handling, session continuation (`--continue`), safe autopilot, and supervisor-session CLI in `src/agent.py`, `src/runner.py`, and `src/cli.py` per `docs/adr/0001-built-in-api-agent-mode.md`:
  - Normalize tool-call `run(script, fix_target?)` (`reply_transport="api_tool"`) and plain-text fallback replies (`reply_transport="text"`) via `extract_reply_block()` (stripping accidental fence/heredoc wrappers, passing the transport mode to step execution so `api_tool` steps only emit the API wrapper reminder if `script` was wrapped in fences/heredocs while plain-text fallback uses the text-block reminder from `F104`, and converting misplaced shell scripts in `fix_target` to sequential steps). When the model returns plain prose without a `run` tool call or runnable block, record `outcome: "awaiting_reply"` rather than auto-closing the session via heuristics.
  - Persist all valid candidate steps under `<session>/<step>/` (`block.sh` or `fix.py`, `plan.md` reasoning, and `meta.json` with `"outcome": "proposed"`, keeping declined `aborted` / `not-run` steps materialized on disk so filesystem artifacts stay 1:1 synchronized with `tool_use` / `tool_result` turns in `<session>/chat.json`).
  - Add `run --continue [session]` (keeping `-c` exclusively for `--clipboard`) to resume an open API session directly from `<session>/chat.json` (opening `START STEP` if a step is `proposed`, sending pending `<step>/out` `tool_result` if completed but unsent, or prompting on `awaiting_reply`).
  - Add `run --step <target_session> --propose | --approve [--propose] | --reject "<reason>" [--propose] | --reply "<message>" [--propose] | --autopilot` (and `--profile <name>` / `-P`, `--autopilot` CLI flags) allowing a supervisor session (`IN_RUN_BLOCK=1`, when `<target_session>` is a distinct worker session initialized outside `IN_RUN_BLOCK=1`) or external orchestrator to inspect, approve, reject, reply to, or autopilot a worker session (surfacing `awaiting_reply` distinctly from `completed`).
  - Implement safe autopilot pausing automatically whenever `src/safety.py` reports risk findings, `RUN_BLOCK_APPROVE_CMD` prompts/rejects, the model enters `awaiting_reply`, or `max_steps` / consecutive failure limits are reached.
  - Add unit tests in `tests/test_agent.py` and `tests/test_runner.py` covering `proposed` and `awaiting_reply` lifecycle, 1:1 `chat.json` step materialization, `--continue`, supervisor `--step` commands, active-session guards, and safe autopilot pause triggers.

# 🎯 [NEXT] F88: Integrate interactive TUI agent loop, model reply prompts, and provider cache stats in cards

- Depends on: F103, F109
- Bump: `MINOR`
- Integrate the built-in API agent loop and token/cache telemetry into the interactive TUI (`src/ui.py`, `src/ui_info.py`, `src/ui_prompt.py`, `src/cli.py`, `src/header.py`, `README.md`) per `docs/adr/0001-built-in-api-agent-mode.md` and `D11`:
  - When a model profile is active, set the default `Enter`/`y` action in `START SESSION` and `END STEP` to `Send to model (<profile>)? [Y/n/a(uto)/c(opy)] · i(nfo) ...` while preserving `c(opy)` for clipboard mode, `p(rompt)` for `$EDITOR` prompt editing, and `run -r` full-reply mode.
  - Stream model reasoning and tool-call progress cleanly in the terminal, transition into `START STEP` (showing `Stats:`, `Reasoning (<stats>):`, single-line `Script (<stats>):`, and safety warnings), and when the model replies with prose only (`outcome: "awaiting_reply"`), present `[r(eply)/d(one)/q(uit)/i(nfo)]` so the user can answer (`r`), manually confirm completion (`d`, promoting the model's summary to `completed_note`), or exit to shell (`q`/`n`).
  - Display provider token usage, cache hit percentage, and remaining Anthropic cache TTL in `Stats:` across `END STEP` and `END SESSION` while keeping fast offline `count_tokens()` estimation for pre-flight cards.
  - Document `--profile` / `-P`, `--continue`, `--autopilot`, `--step`, `config.json` / `models.json`, and `RUN_BLOCK_MODEL*` / `RUN_BLOCK_CACHE` in `src/header.py` (`--help`), `agents/run.md`, and `README.md`, and add unit tests in `tests/test_ui.py` and `tests/test_cli.py`.

# ⚪ [NEW] F111: Move TestConfigSettings from tests/test_runner.py into tests/test_config.py

Problem: `TestConfigSettings` (settings precedence, profiles, API key scrubbing, `_clean_out_text`) lives in `tests/test_runner.py` although it exercises `src/config.py` and `src/safety.py`.
Impact: breaks the mirrored test layout; config regressions surface under the runner suite.

# ⏸️ [HOLD] D9: Design machine-readable runner contract (--json step output and plan/execute handshake) — *Defer external machine-readable runner contract until an external client is needed; built-in API agent mode (D10) runs in-process*

- Depends on: F79, F83, F88
- Design contract to let an external API/TUI/IDE client drive `run` cleanly without parsing TUI frames or overloading `-y`/`--yes`.
- Align with `F83` step outcome metadata in `<session>/<step>/meta.json` (`outcome`: `ok`/`failed`/`syntax-error`/`not-run`/`aborted`/`saved`, `exit_code`, `duration_ms`, `reason`, `fix_target`) and `D10`/`F88` in-process step structures to evaluate structured `--json` execution output for `<session>/<step>` (including safety findings, auto-repair/renumber notes, and clean `[sN/k]` LLM payload) and a two-phase `plan -> approve -> execute` CLI handshake for external clients.
- Coordinate with `F42` (`--done` completion state) and `F46` (`bundle_plan` metadata).

# 🔎 [REVIEW] F93: Split src/runner.py into src/reply.py, src/fix.py, src/inspect_cmd.py, and src/runner.py

- Depends on: F94, B15, B16, D11, F101, F104, F108, F107
- Split `src/runner.py` (~4,100 lines) along the single-responsibility module boundaries decided in `D11`:
  - `src/reply.py`: model reply block extraction and split-payload reassembly (`extract_reply_block()`, `_reassemble_split_payload_with_meta()`, `normalize_api_tool_script()`, `format_protocol_reminder_lines()`, `_detect_output_prompt_injection_warning()`, `cmd_run_reply()`).
  - `src/fix.py`: Python `--fix` AST anchor inspection, repair hints, syntax context, consecutive failure tracking, and `cmd_fix()`.
  - `src/inspect_cmd.py`: session and step inspection/lifecycle commands (`cmd_list()`, `cmd_show()`, `cmd_clean()`, `cmd_sandbox()`, `cmd_done()`, `render_end_session_card()`, `_step_status()`, `_warn_if_state_oversized()`).
  - `src/runner.py`: core step execution engine (`_ProgressLineFilter`, `_prepare_progress_script()`, `_validate_step_script_syntax()`, `_resolve_python_stdin_tracebacks()`, `run_script()`, `not_run_exit()`, `cmd_normal()`, `cmd_retry()`).
- Tighten `extract_reply_block()` edge cases during the `src/reply.py` split:
  - When a `RUN_BLOCK`/`RUN_FIX` terminator is omitted and the block closes with a plain Markdown fence followed by trailing prose that itself contains another fenced code block, stop at the first closing fence outside inner heredocs rather than swallowing the trailing fenced example via `close_fence_before_next[-1]`.
  - Track post-chosen duplicate block references alongside distinct trailing blocks so `ignored_trailing_refs` and `total_discarded_blocks` in `format_protocol_reminder_lines()` stay consistent when both a duplicate block and another trailing block appear after the chosen block (and exclude pre-chosen template duplicates when `chosen_idx > 0`).
- Register `src/reply.py`, `src/fix.py`, and `src/inspect_cmd.py` in `build.py` `MODULE_ORDER`, rebuild `./run` via `python3 build.py`, and keep the offline test suite green.

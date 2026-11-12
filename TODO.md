# run_block — active tasks and operational state

[README.md](README.md) documents installation and CLI usage; [AGENTS.md](AGENTS.md)
defines the rules and workflow for an AI agent working on this repository.

Task heading format: `### <emoji> [<STATUS>] <ID>: <title>`
(`⚪ [NEW]`, `🔵 [WIP]`, `⏸️ [HOLD]`, `❓ [QUESTION]`, `✅ [DONE]`, `❌ [CANCELED]`).

## Resume

Written 2026-11-12. Released `run_block` `v0.5.0`:
- Standalone zero-dependency Python 3 CLI (`run_block`) with one-liner installers (`install.sh` for Linux/macOS, `install.ps1` for Windows PowerShell 7+) and command-name conflict resolution.
- Pre-execution `BLOCK PLAN` (shows `Workdir`, `cd` targets, and ordered `Operations` across Bash and embedded Python AST) + 6-category `Safety warnings` scanner with `tcflush` input protection.
- Single-keystroke `Enter` (copy) / `Esc` (skip) clipboard prompt with byte size and Claude/GPT/Gemini token counts.
- Session and block navigation (`--list` / `-l`, `--show`, `--retry` / `--rerun`, `--start`).
- Configuration file support (`~/.config/run_block/config`, `--config`, `--init-config`).
- Automated agent instructions management (`--agents-install [FILE]` and `--agents` with `<!-- run_block:start ... -->` markers) and self-update (`--update`, `--check-update`).
- GitHub Actions CI (`ubuntu-latest`, `macos-latest`) and automatic GitHub Releases on `v*` tags.

To continue development in a new chat: attach `AGENTS.md` and `TODO.md`.

## Tasks

### ⚪ [NEW] F1: Native PowerShell (`pwsh`) block execution mode on Windows

Allow `shell = pwsh` in `~/.config/run_block/config` so Windows users in PowerShell 7
can execute native PowerShell blocks in addition to Bash blocks.

### ⚪ [NEW] F2: Custom user-defined safety rules in config

Allow adding custom regex patterns or overriding risk categories in
`~/.config/run_block/config`.

### ⚪ [NEW] F3: Session cleanup command (`--clean`)

Add `run_block --clean [--keep N | --all]` to prune old session directories in
`/tmp/run_block` (navigation via `--list`, `--show`, and `--retry` is already shipped in `v0.5.0`).

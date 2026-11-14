def open_tty():
    tty_in_name = "CONIN$" if os.name == "nt" else "/dev/tty"
    tty_out_name = "CONOUT$" if os.name == "nt" else "/dev/tty"
    return (
        open(tty_out_name, "w", encoding="utf-8", errors="replace"),
        open(tty_in_name, "r", encoding="utf-8", errors="replace"),
    )


def flush_tty_input(tty_r) -> None:
    if HAS_PTY and termios is not None:
        try:
            termios.tcflush(tty_r.fileno(), termios.TCIFLUSH)
        except Exception:
            pass


def read_clipboard_key(tty_r) -> str:
    """Wait for a single key: returns 'copy', 'skip', or 'view'."""
    flush_tty_input(tty_r)
    if not HAS_PTY or termios is None or tty is None:
        ans = tty_r.readline().strip().lower()
        if ans in ("v", "view", "e", "edit"):
            return "view"
        return "skip" if ans in ("n", "no", "esc", "\x1b") else "copy"
    try:
        fd = tty_r.fileno()
        old_attrs = termios.tcgetattr(fd)
    except Exception:
        ans = tty_r.readline().strip().lower()
        return "view" if ans in ("v", "view", "e", "edit") else ("skip" if ans in ("n", "no", "esc", "\x1b") else "copy")
    try:
        tty.setraw(fd, termios.TCSANOW)
        while True:
            ch = os.read(fd, 1)
            if not ch:
                return "skip"
            if ch in (b"v", b"V", b"e", b"E"):
                return "view"
            if ch in (b"\r", b"\n", b"y", b"Y"):
                return "copy"
            if ch in (b"n", b"N", b"q", b"Q", b"\x03", b"\x04"):
                return "skip"
            if ch == b"\x1b":
                # Distinguish standalone Esc from multi-byte escape sequences (like arrow keys)
                rlist, _, _ = select.select([fd], [], [], 0.05)
                if rlist:
                    os.read(fd, 32)
                    continue
                return "skip"
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)
        except Exception:
            pass


def _wrap_labeled_items(items: list[tuple[str, str]], max_width: int, indent: str = "  ") -> list[str]:
    if not items:
        return []
    tag_w = max(len(f"[{k}]") for k, _ in items)
    out: list[str] = []
    for k, v in items:
        tag = f"[{k}]".ljust(tag_w)
        prefix = f"{indent}{tag}  "
        sub_indent = " " * len(prefix)
        avail = max(24, max_width - len(prefix))
        wrapped = textwrap.wrap(v, width=avail, break_long_words=True, break_on_hyphens=False) or [v]
        out.append(prefix + wrapped[0])
        for cont in wrapped[1:]:
            out.append(sub_indent + cont)
    return out


def format_safety_box(
    label: str,
    findings: list[dict[str, object]],
    default_yes: bool = False,
    summary: dict[str, object] | None = None,
    note: str = "",
    script_path: Path | None = None,
) -> tuple[str, int, int]:
    meta_str = str(summary.get("meta", "")) if summary else ""
    title = f" {label} · BLOCK PLAN "
    prompt_suffix = "[Y/n/v(iew)]:" if default_yes else "[y/n/v(iew)]:"
    prompt_line = f"-> Execute this block? {prompt_suffix}"
    term_cols = shutil.get_terminal_size((100, 24)).columns
    max_row_len = max(64, term_cols - 6)

    content_lines: list[str] = []
    if summary:
        wdir = str(summary.get("work_dir") or "")
        cd_dirs = list(summary.get("cd_dirs") or [])
        sb_mode = str(summary.get("sandbox") or "off")
        if wdir:
            wline = f"Workdir: {wdir}" + (f"  (cd -> {', '.join(cd_dirs)})" if cd_dirs else "")
            content_lines.extend(textwrap.wrap(wline, width=max_row_len) or [wline])
        if sb_mode and sb_mode != "off":
            sb_line = f"Sandbox: {format_sandbox_header(sb_mode)}"
            content_lines.extend(textwrap.wrap(sb_line, width=max_row_len) or [sb_line])
        if meta_str:
            content_lines.append(f"Script: {meta_str}")
        ops = list(summary.get("operations") or [])
        op_groups = list(summary.get("operation_groups") or [])
        has_subdirs = any(bool(g_dir) for g_dir, _ in op_groups)
        if ops:
            if content_lines:
                content_lines.append("")
            content_lines.append("Operations:")
            if has_subdirs and op_groups:
                for idx, (g_dir, g_items) in enumerate(op_groups):
                    if idx > 0:
                        content_lines.append("")
                    dir_hdr = g_dir if g_dir else (wdir or ".")
                    content_lines.append(f"  {dir_hdr}:")
                    content_lines.extend(_wrap_labeled_items(g_items, max_row_len, indent="    "))
            else:
                content_lines.extend(_wrap_labeled_items(ops, max_row_len, indent="  "))

    if findings:
        if content_lines:
            content_lines.append("")
        content_lines.append(f"Safety warnings ({len(findings)}):")
        warn_items = [(str(f["category"]), str(f["snippet"])) for f in findings]
        content_lines.extend(_wrap_labeled_items(warn_items, max_row_len, indent="  "))

    if note.strip():
        if content_lines:
            content_lines.append("")
        content_lines.append("Analyzer:")
        for nline in note.strip().splitlines():
            content_lines.extend(
                textwrap.wrap(nline, width=max_row_len - 2, initial_indent="  ", subsequent_indent="  ")
                or [f"  {nline}"]
            )

    run_target = str(script_path) if script_path is not None else label
    status_lines = (
        f"✓ Running {run_target} ...",
        f"✗ Aborted (--retry {label})",
    )
    inner_width = max(
        display_width(title),
        display_width(prompt_line),
        *(display_width(s) for s in status_lines),
        *(display_width(b) for b in content_lines),
    )
    dashes = max(1, inner_width + 2 - display_width(title) - 1)
    top = f"┌─{title}{'─' * dashes}┐"
    bottom = f"└─{'─' * inner_width}─┘"
    rows = [pad_box_line(b, inner_width) for b in content_lines]
    if content_lines:
        rows.append(pad_box_line("", inner_width))
    rows.append(pad_box_line(prompt_line, inner_width))
    box = "\n".join([top, *rows, bottom])
    cursor_col_offset = 2 + display_width(prompt_line)
    return box, inner_width, cursor_col_offset


def format_info_box(title: str, content_lines: list[str]) -> str:
    hdr = title if title.startswith(" ") else f" {title} "
    inner_width = max(
        display_width(hdr),
        *(display_width(b) for b in content_lines),
    )
    dashes = max(1, inner_width + 2 - display_width(hdr) - 1)
    top = f"┌─{hdr}{'─' * dashes}┐"
    bottom = f"└─{'─' * inner_width}─┘"
    rows = [pad_box_line(b, inner_width) for b in content_lines] or [pad_box_line("", inner_width)]
    return "\n".join([top, *rows, bottom])


def format_prompt_box(
    title: str,
    content_lines: list[str],
    prompt_line: str,
    status_lines: list[str] | tuple[str, ...] = (),
) -> tuple[str, int, int]:
    hdr = title if title.startswith(" ") else f" {title} "
    inner_width = max(
        display_width(hdr),
        display_width(prompt_line),
        *(display_width(s) for s in status_lines),
        *(display_width(b) for b in content_lines),
    )
    dashes = max(1, inner_width + 2 - display_width(hdr) - 1)
    top = f"┌─{hdr}{'─' * dashes}┐"
    bottom = f"└─{'─' * inner_width}─┘"
    rows = [pad_box_line(b, inner_width) for b in content_lines]
    if content_lines:
        rows.append(pad_box_line("", inner_width))
    rows.append(pad_box_line(prompt_line, inner_width))
    box = "\n".join([top, *rows, bottom])
    cursor_col_offset = 2 + display_width(prompt_line)
    return box, inner_width, cursor_col_offset


def prompt_yes_no_box(
    title: str,
    content_lines: list[str],
    question: str,
    default_yes: bool = False,
    yes_status: str = "✓ Confirmed by user.",
    no_status: str = "✗ Canceled by user.",
    tty_streams: tuple[object, object] | None = None,
) -> bool:
    suffix = "[Y/n]:" if default_yes else "[y/N]:"
    prompt_line = f"-> {question} {suffix}"
    box, inner_width, cursor_offset = format_prompt_box(
        title, content_lines, prompt_line, status_lines=(yes_status, no_status)
    )
    bottom = f"└─{'─' * inner_width}─┘"
    try:
        if tty_streams is not None:
            tty_w, tty_r = tty_streams
            close_after = False
        else:
            tty_w, tty_r = open_tty()
            close_after = True
        try:
            tty_w.write(f"{box}\r\033[1A\033[{cursor_offset}C")
            tty_w.flush()
            while True:
                action = read_confirm_key(tty_r, default_yes=default_yes)
                if action == "yes":
                    approved = True
                    break
                if action == "no":
                    approved = False
                    break
            status_line = yes_status if approved else no_status
            tty_w.write(f"\r{pad_box_line(status_line, inner_width)}\n{bottom}\n")
            tty_w.flush()
            return approved
        finally:
            if close_after:
                tty_w.close()
                tty_r.close()
    except OSError:
        return default_yes


def resolve_editor_command() -> list[str]:
    cfg_ed, _ = get_setting("editor")
    if cfg_ed and cfg_ed.lower() != "auto":
        return shlex.split(cfg_ed)
    for env_k in ("VISUAL", "EDITOR"):
        val = os.environ.get(env_k, "").strip()
        if val:
            return shlex.split(val)
    for candidate in ("vim", "vi", "less", "nano", "more"):
        if shutil.which(candidate):
            return [candidate]
    return ["vi"]


def open_script_in_editor(script_path: Path, tty_r, tty_w) -> None:
    cmd = resolve_editor_command() + [str(script_path)]
    try:
        subprocess.run(cmd, stdin=tty_r, stdout=tty_w, stderr=tty_w, check=False)
    except Exception as exc:
        tty_w.write(f"\n[editor error: {exc}]\n")
        tty_w.flush()


def read_confirm_key(tty_r, default_yes: bool) -> str:
    """Reads a single key: returns 'yes', 'no', or 'view'."""
    flush_tty_input(tty_r)
    if not HAS_PTY or termios is None or tty is None:
        ans = tty_r.readline().strip().lower()
        if ans in ("v", "view", "e", "edit"):
            return "view"
        if default_yes and ans in ("", "y", "yes"):
            return "yes"
        if not default_yes and ans in ("y", "yes"):
            return "yes"
        if ans in ("n", "no", "q", "esc"):
            return "no"
        return "invalid"
    try:
        fd = tty_r.fileno()
        old_attrs = termios.tcgetattr(fd)
    except Exception:
        ans = tty_r.readline().strip().lower()
        return "view" if ans in ("v", "view", "e", "edit") else ("yes" if ans in ("y", "yes") else "no")
    try:
        tty.setraw(fd, termios.TCSANOW)
        while True:
            ch = os.read(fd, 1)
            if not ch:
                return "no"
            if ch in (b"v", b"V", b"e", b"E"):
                return "view"
            if ch in (b"y", b"Y"):
                return "yes"
            if default_yes and ch in (b"\r", b"\n"):
                return "yes"
            if ch in (b"n", b"N", b"q", b"Q", b"\x03", b"\x04"):
                return "no"
            if ch == b"\x1b":
                rlist, _, _ = select.select([fd], [], [], 0.05)
                if rlist:
                    os.read(fd, 32)
                    continue
                return "no"
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)
        except Exception:
            pass


def confirm_execution(
    label: str,
    script_text: str,
    summary: dict[str, object] | None = None,
    script_path: Path | None = None,
    auto_yes: bool = False,
) -> tuple[bool, str]:
    if in_run_block():
        return True, ""
    findings = scan_script_risks(script_text)
    note = ""
    approve_decision = ""
    approve_cmd, _ = get_setting("approve_cmd")
    if approve_cmd:
        wdir = Path(str(summary.get("work_dir"))) if summary and summary.get("work_dir") else get_work_dir()
        plan_obj = analyze_script(script_text, work_dir=wdir, label=label, check_syntax=False)
        approve_decision, note = run_approve_cmd(approve_cmd, label, script_text, plan_obj, script_path=script_path)
        if approve_decision == "reject":
            return False, (note or "rejected by RUN_BLOCK_APPROVE_CMD")
        if approve_decision == "approve":
            if findings and (auto_yes or not sys.stdout.isatty() or no_clipboard()):
                for f in findings:
                    sys.stdout.write(f"[{label}] safety warning [{f['category']}]: {f['snippet']}\n")
                sys.stdout.flush()
            return True, note
    if auto_yes or not sys.stdout.isatty() or no_clipboard():
        if findings:
            for f in findings:
                sys.stdout.write(f"[{label}] safety warning [{f['category']}]: {f['snippet']}\n")
            sys.stdout.flush()
        return True, note
    default_yes = (len(findings) == 0 and approve_decision != "prompt")
    box, inner_width, cursor_offset = format_safety_box(
        label,
        findings,
        default_yes=default_yes,
        summary=summary,
        note=note,
        script_path=script_path,
    )
    bottom = f"└─{'─' * inner_width}─┘"
    prompt_suffix = "[Y/n/v(iew)]:" if default_yes else "[y/n/v(iew)]:"
    prompt_line = f"-> Execute this block? {prompt_suffix}"
    try:
        tty_w, tty_r = open_tty()
        with tty_w, tty_r:
            tty_w.write(f"{box}\r\033[1A\033[{cursor_offset}C")
            tty_w.flush()
            while True:
                action = read_confirm_key(tty_r, default_yes=default_yes)
                if action == "view":
                    if script_path is not None and script_path.is_file():
                        open_script_in_editor(script_path, tty_r, tty_w)
                        p_offset = 2 + display_width(prompt_line)
                        tty_w.write(f"\r{pad_box_line(prompt_line, inner_width)}\n{bottom}\r\033[1A\033[{p_offset}C")
                        tty_w.flush()
                    continue
                if action == "yes":
                    approved = True
                    break
                if action == "no":
                    approved = False
                    break
            run_target = str(script_path) if script_path is not None else label
            status_line = f"✓ Running {run_target} ..." if approved else f"✗ Aborted (--retry {label})"
            tty_w.write(f"\r{pad_box_line(status_line, inner_width)}\n{bottom}\n")
            tty_w.flush()
            return approved, ("" if approved else "USER_ABORTED")
    except OSError:
        return True, note


# --- Built-in token and byte statistics ---
_ENC = None
_ENC_TRIED = False


def gpt_encoder():
    global _ENC, _ENC_TRIED
    if not _ENC_TRIED:
        _ENC_TRIED = True
        try:
            import tiktoken  # type: ignore[import-not-found]
            _ENC = tiktoken.get_encoding("o200k_base")
        except Exception:
            _ENC = None
    return _ENC


def count_tokens(data: bytes) -> dict[str, int | bool]:
    text = data.decode("utf-8", "replace")
    chars = len(text)
    lines = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
    enc = gpt_encoder()
    if enc is not None:
        gpt = len(enc.encode(text, disallowed_special=()))
    else:
        gpt = math.ceil(chars / 4)
    return {
        "bytes": len(data),
        "lines": lines,
        "claude": math.ceil(chars / 3.5),
        "gpt": gpt,
        "gpt_exact": enc is not None,
        "gemini": math.ceil(chars / 4),
    }


def _human_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    return f"{num_bytes / 1024:.1f} KB"


def _human_tok(n: int) -> str:
    if n < 1000:
        return f"{n}"
    return f"{n / 1000:.1f}k"


def format_stats(data: bytes) -> str:
    s = count_tokens(data)
    lines = int(s["lines"])
    sz = _human_size(int(s["bytes"]))
    lo = min(int(s["gpt"]), int(s["claude"]))
    hi = max(int(s["gpt"]), int(s["claude"]))
    tok_str = f"~{_human_tok(lo)}–{_human_tok(hi)} tokens" if lo != hi else f"~{_human_tok(lo)} tokens"
    line_lbl = f"{lines} line{'s' if lines != 1 else ''}"
    return f"{line_lbl} · {sz} · {tok_str}"


def stats_line(path: Path) -> str | None:
    enabled, _ = get_setting("token_stats")
    if enabled == "false":
        return None
    try:
        return format_stats(path.read_bytes())
    except Exception:
        return None


ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
CR_LINE_RE = re.compile(r"[^\n]*\r(?!\n)")


def resolve_clipboard_target(out_path: Path, full_output: str) -> Path:
    matches = re.findall(
        r"^(?:\[[A-Za-z0-9._-]+\] Attach:|│?\s*Bundle:)\s*(\S+?)\s*(?:│)?$",
        full_output,
        flags=re.MULTILINE,
    )
    if matches:
        candidate = Path(matches[-1])
        if candidate.is_file():
            return candidate
    return out_path


def clipboard_command(out_path: Path) -> tuple[list[str], str] | None:
    if shutil.which("xclip") and os.environ.get("DISPLAY"):
        return ["xclip", "-selection", "clipboard"], f"xclip -selection clipboard < {out_path}"
    if shutil.which("wl-copy") and os.environ.get("WAYLAND_DISPLAY"):
        return ["wl-copy"], f"wl-copy < {out_path}"
    if shutil.which("pbcopy"):
        return ["pbcopy"], f"pbcopy < {out_path}"
    if shutil.which("xsel") and os.environ.get("DISPLAY"):
        return ["xsel", "--clipboard", "--input"], f"xsel --clipboard --input < {out_path}"
    if shutil.which("clip.exe"):
        return ["clip.exe"], f"clip.exe < {out_path}"
    return None


def copy_file_to_clipboard(cmd: list[str], out_path: Path) -> bool:
    try:
        with open(out_path, "rb") as f_in:
            r = subprocess.run(
                cmd,
                stdin=f_in,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
        return r.returncode == 0
    except Exception:
        return False


def display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in text)


def pad_box_line(text: str, inner_width: int) -> str:
    pad = max(0, inner_width - display_width(text))
    return f"│ {text}{' ' * pad} │"


def build_box_body_lines(
    out_path: Path,
    rc: int | None = None,
    stats: str | None = None,
    extra_lines: list[str] | None = None,
) -> list[str]:
    if extra_lines is not None:
        body_lines = list(extra_lines)
    else:
        body_lines = []
        if rc is not None and rc != 0:
            body_lines.append(f"Exit: {rc}")
        body_lines.append(f"Output: {out_path}")
    if stats and not any(line.startswith("Stats:") for line in body_lines):
        body_lines.append(f"Stats: {stats}")
    return body_lines


def format_clipboard_box(
    label: str,
    out_path: Path,
    ok: bool = True,
    rc: int | None = None,
    stats: str | None = None,
    title_kind: str = "END",
    extra_lines: list[str] | None = None,
    cmd_str: str | None = None,
) -> tuple[str, int, int]:
    title = f" {label} · {title_kind} "
    body_lines = build_box_body_lines(out_path, rc=rc, stats=stats, extra_lines=extra_lines)
    prompt_line = "-> Copy to clipboard? [Enter/v(iew)/Esc]:"
    status_lines = [
        f"✓ Copied {out_path} to clipboard.",
        "Skipped clipboard copy.",
    ]
    if cmd_str:
        status_lines.append(f"✗ Clipboard copy failed; run: {cmd_str}")
    inner_width = max(
        display_width(title),
        display_width(prompt_line),
        *(display_width(s) for s in status_lines),
        *(display_width(b) for b in body_lines),
    )
    dashes = max(1, inner_width + 2 - display_width(title) - 1)
    top = f"┌─{title}{'─' * dashes}┐"
    bottom = f"└─{'─' * inner_width}─┘"
    rows = [pad_box_line(b, inner_width) for b in body_lines]
    rows.append(pad_box_line("", inner_width))
    rows.append(pad_box_line(prompt_line, inner_width))
    box = "\n".join([top, *rows, bottom])
    cursor_col_offset = 2 + display_width(prompt_line)
    return box, inner_width, cursor_col_offset


def offer_clipboard_copy(
    label: str,
    out_path: Path,
    ok: bool = True,
    rc: int | None = None,
    title_kind: str = "END",
    extra_lines: list[str] | None = None,
) -> None:
    if in_run_block():
        return
    mode = clipboard_mode()
    if mode == "never":
        return
    clip = clipboard_command(out_path)
    if clip is None:
        return
    cmd, cmd_str = clip
    if mode == "auto":
        if copy_file_to_clipboard(cmd, out_path):
            sys.stdout.write(f"✓ Copied {out_path} to clipboard.\n")
        else:
            sys.stdout.write(f"[{label}] clipboard: {cmd_str}\n")
        sys.stdout.flush()
        return
    if not sys.stdout.isatty():
        sys.stdout.write(f"[{label}] clipboard: {cmd_str}\n")
        sys.stdout.flush()
        return
    box, inner_width, cursor_offset = format_clipboard_box(
        label,
        out_path,
        ok=ok,
        rc=rc,
        stats=stats_line(out_path),
        title_kind=title_kind,
        extra_lines=extra_lines,
        cmd_str=cmd_str,
    )
    bottom = f"└─{'─' * inner_width}─┘"
    line2 = "-> Copy to clipboard? [Enter/v(iew)/Esc]:"
    try:
        tty_w, tty_r = open_tty()
        with tty_w, tty_r:
            tty_w.write(f"\n{box}\r\033[1A\033[{cursor_offset}C")
            tty_w.flush()
            while True:
                action = read_clipboard_key(tty_r)
                if action == "view":
                    if out_path.is_file():
                        open_script_in_editor(out_path, tty_r, tty_w)
                        tty_w.write(f"\r{pad_box_line(line2, inner_width)}\n{bottom}\r\033[1A\033[{cursor_offset}C")
                        tty_w.flush()
                    continue
                if action == "copy":
                    if copy_file_to_clipboard(cmd, out_path):
                        status_line = f"✓ Copied {out_path} to clipboard."
                    else:
                        status_line = f"✗ Clipboard copy failed; run: {cmd_str}"
                else:
                    status_line = "Skipped clipboard copy."
                break
            tty_w.write(f"\r{pad_box_line(status_line, inner_width)}\n{bottom}\n")
            tty_w.flush()
    except OSError:
        sys.stdout.write(f"[{label}] clipboard: {cmd_str}\n")
        sys.stdout.flush()

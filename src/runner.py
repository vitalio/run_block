def ensure_base() -> Path:
    base = default_base_dir()
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        base.chmod(0o700)
    except OSError:
        pass
    return base


def next_session_name(base: Path) -> str:
    used = set()
    for p in base.iterdir():
        m = re.fullmatch(r"s(\d+)", p.name)
        if m:
            used.add(int(m.group(1)))
    n = 1
    while n in used:
        n += 1
    return f"s{n}"


def start_session(name: str | None = None, force: bool = False, sandbox_mode: str | None = None) -> Path:
    base = ensure_base()
    _warn_if_state_oversized(base)
    if not name:
        name = next_session_name(base)
    if not re.fullmatch(r"[A-Za-z0-9._-]+", name):
        raise SystemExit(f"{prog_name()}: invalid session name: {name!r}")
    sdir = base / name
    if sdir.exists():
        if not force:
            raise SystemExit(f"{prog_name()}: session {sdir} already exists (use --force to overwrite)")
        shutil.rmtree(sdir)
    sdir.mkdir(mode=0o700, parents=True)
    ensure_session_bundle(sdir, sandbox_mode=sandbox_mode)
    return sdir


def parse_ref(ref: str, allow_fix_step: bool) -> tuple[str, str]:
    pattern = r"^([A-Za-z0-9._-]+)/(\d+(?:_\d+)?)$" if allow_fix_step else r"^([A-Za-z0-9._-]+)/(\d+)$"
    m = re.fullmatch(pattern, ref.strip())
    if not m:
        kind = "<session>/<step> (e.g. s1/2 or s1/2_1)" if allow_fix_step else "<session>/<step> (e.g. s1/1)"
        raise SystemExit(f"{prog_name()}: invalid block reference {ref!r}; expected {kind}")
    return m.group(1), m.group(2)


def next_free_step(sdir: Path, min_step: int = 1) -> int:
    used: set[int] = set()
    if sdir.is_dir():
        for p in sdir.iterdir():
            if p.is_dir():
                m = re.fullmatch(r"(\d+)(?:_\d+)?", p.name)
                if m:
                    used.add(int(m.group(1)))
    candidate = max(min_step, (max(used) + 1) if used else 1)
    while candidate in used:
        candidate += 1
    return candidate


def first_missing_step(sdir: Path) -> int:
    n = 1
    while True:
        step_dir = _step_dir(sdir, str(n))
        has_script = _find_step_script(sdir, str(n)).exists()
        has_out = (step_dir / "out").exists()
        is_aborted = (step_dir / "aborted").exists()
        if (not has_script and not has_out) or is_aborted:
            return n
        n += 1


def _rewrite_script_step_header(script_text: str, old_label: str, new_label: str) -> str:
    lines = script_text.splitlines(keepends=True)
    if not lines:
        return script_text
    pat = re.compile(
        rf"^(\s*#\s*(?:run(?:_block)?|Block|Next-Block)\s*:\s*){re.escape(old_label)}(\s*)$"
    )
    for idx in range(min(3, len(lines))):
        line_body = lines[idx].rstrip("\r\n")
        eol = lines[idx][len(line_body) :]
        m = pat.match(line_body)
        if m:
            lines[idx] = f"{m.group(1)}{new_label}{m.group(2)}{eol}"
            break
    return "".join(lines)


def next_fix_step(step: str, sdir: Path | None = None) -> str:
    base = step.split("_", 1)[0]
    min_next = 1
    if "_" in step:
        _, sub = step.split("_", 1)
        if sub.isdigit():
            min_next = int(sub) + 1
    if sdir is not None and sdir.is_dir():
        max_n = 0
        pat = re.compile(rf"^{re.escape(base)}_(\d+)$")
        for p in sdir.iterdir():
            m = pat.match(p.name)
            if m and p.is_dir():
                max_n = max(max_n, int(m.group(1)))
        return f"{base}_{max(min_next, max_n + 1)}"
    return f"{base}_{min_next}"


def write_private(path: Path, content: str, overwrite: bool = False) -> None:
    flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if overwrite else os.O_EXCL)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)


_EMBEDDED_PY_HEREDOC_RE = re.compile(r"\bpython3?(?:\s+[^\n]*?)?<<-?\s*['\"]?([A-Za-z0-9_]+)['\"]?")
_STDIN_TB_LINE_RE = re.compile(r'File "<stdin>", line (\d+)(?:, in ([^\n]+))?')


def _extract_python_heredoc_bodies(script_text: str) -> list[list[str]]:
    bodies: list[list[str]] = []
    eof_token: str | None = None
    strip_tabs = False
    cur_lines: list[str] = []
    for raw in script_text.splitlines():
        if eof_token is not None:
            cmp_line = raw.lstrip("\t") if strip_tabs else raw
            if cmp_line.strip() == eof_token:
                bodies.append(cur_lines)
                eof_token = None
                strip_tabs = False
                cur_lines = []
            else:
                cur_lines.append(cmp_line if strip_tabs else raw)
            continue
        m = _EMBEDDED_PY_HEREDOC_RE.search(raw)
        if m:
            eof_token = m.group(1)
            strip_tabs = "<<-" in raw
            cur_lines = []
    if eof_token is not None and cur_lines:
        bodies.append(cur_lines)
    return bodies


def _resolve_python_stdin_tracebacks(label: str, script_text: str, output_text: str) -> list[str]:
    matches = _STDIN_TB_LINE_RE.findall(output_text)
    if not matches:
        return []
    heredocs = _extract_python_heredoc_bodies(script_text)
    if not heredocs:
        return []
    resolved: list[str] = []
    seen: set[tuple[int, str]] = set()
    for raw_ln, raw_func in matches:
        try:
            lineno = int(raw_ln)
        except ValueError:
            continue
        if lineno < 1:
            continue
        func_name = (raw_func or "").strip()
        chosen_body: list[str] | None = None
        if len(heredocs) == 1:
            if lineno <= len(heredocs[0]):
                chosen_body = heredocs[0]
        else:
            if func_name and func_name != "<module>":
                def_pat = re.compile(rf"^\s*(?:async\s+)?def\s+{re.escape(func_name)}\b")
                for body in reversed(heredocs):
                    if lineno <= len(body) and any(def_pat.match(ln) for ln in body):
                        chosen_body = body
                        break
            if chosen_body is None:
                for body in reversed(heredocs):
                    if lineno <= len(body):
                        chosen_body = body
                        break
        if chosen_body is None:
            continue
        src_line = chosen_body[lineno - 1].strip()
        if not src_line:
            continue
        key = (lineno, src_line)
        if key in seen:
            continue
        seen.add(key)
        resolved.append(f"[{label}] <stdin> line {lineno}: {src_line}")
    return resolved


def not_run_exit(
    label: str,
    sdir: Path,
    step_name: str,
    out_path: Path,
    msg: str,
    rc: int = 2,
    headless: bool = False,
    fix_target: str | None = None,
    outcome: str | None = "not-run",
    reasoning: str | None = None,
) -> int:
    step_dir = _step_dir(sdir, step_name)
    step_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    line = msg if msg.endswith("\n") else msg + "\n"
    clean_msg = msg.strip()
    prefix = f"[{label}] NOT RUN:"
    detail = clean_msg[len(prefix):].strip() if clean_msg.startswith(prefix) else clean_msg
    detail_lines = detail.splitlines() or [detail]
    err_target = step_dir / "error" if out_path.exists() else out_path
    try:
        write_private(err_target, line, overwrite=True)
        if outcome and err_target == out_path:
            write_step_meta(
                step_dir,
                duration_ms=0,
                exit_code=rc,
                outcome=outcome,
                reason=detail_lines[0],
                fix_target=fix_target,
                reasoning=reasoning,
            )
    except Exception:
        pass
    is_headless = headless or os.environ.get("RUN_BLOCK_HEADLESS") == "1"
    if is_headless:
        sys.stdout.write(line)
        sys.stdout.flush()
        return rc
    body_lines: list[str] = []
    if fix_target:
        body_lines.append(f"Target: {fix_target} -> {label}")
    body_lines.append(f"Reason: {detail_lines[0]}")
    stop_pat = re.compile(rf"^(?:\[{re.escape(label)}\]\s*)?STOP --fix:\s*(.*)$")
    for dline in detail_lines[1:]:
        m_stop = stop_pat.match(dline.strip())
        if m_stop:
            body_lines.append(f"Guard: {m_stop.group(1).strip()}")
        else:
            body_lines.append(f"  {dline}")
    body_lines.append(f"Output: {err_target}")
    can_prompt_clip = (
        not in_run_block()
        and sys.stdout.isatty()
        and clipboard_mode() == "prompt"
        and clipboard_command(err_target) is not None
    )
    if can_prompt_clip:
        offer_clipboard_copy(label, err_target, rc=rc, title_kind="NOT RUN", extra_lines=body_lines, sdir=sdir)
    else:
        full_body = build_box_body_lines(
            err_target, rc=rc, stats=stats_line(err_target), extra_lines=body_lines, label=label, sdir=sdir
        )
        sys.stdout.write(format_info_box("NOT RUN", full_body) + "\n")
        sys.stdout.flush()
        if not in_run_block():
            offer_clipboard_copy(label, err_target, rc=rc, title_kind="NOT RUN", extra_lines=body_lines, sdir=sdir)
    return rc


def _clean_out_text(text: str) -> str:
    cleaned = ANSI_RE.sub("", text).replace("\r\n", "\n")
    if "\r" in cleaned:
        cleaned = CR_LINE_RE.sub("", cleaned)
    return cleaned


class _ProgressLineFilter:
    def __init__(
        self,
        step_map: dict[int, dict[str, object]],
        total_steps: int,
        marker_prefix: str = "__RB_STEP__:",
        clock: object = None,
        is_tty: bool | None = None,
    ) -> None:
        self.step_map = step_map
        self.total_steps = total_steps
        self.marker_prefix = marker_prefix
        self.buf = ""
        self._marker_re = re.compile(rf"^(.*?){re.escape(marker_prefix)}(\d+)\r?$")
        self._clock = clock if callable(clock) else time.monotonic
        if is_tty is None:
            try:
                self._is_tty = bool(sys.stdout.isatty())
            except Exception:
                self._is_tty = False
        else:
            self._is_tty = bool(is_tty)
        self.active_step: int | None = None
        self._active_started: float | None = None
        self._active_has_output: bool = False
        self.step_durations: dict[int, float] = {}
        self.step_order: list[int] = []
        self.line_base = 0
        self._op_text: dict[int, list[str]] = {}
        self._pre_text: list[str] = []
        self._at_line_start: bool = True

    @staticmethod
    def _truncate_width(text: str, max_w: int) -> str:
        if display_width(text) <= max_w:
            return text
        if max_w <= 3:
            out_chars: list[str] = []
            cur_w = 0
            for ch in text:
                cw = display_width(ch)
                if cur_w + cw > max(0, max_w):
                    break
                out_chars.append(ch)
                cur_w += cw
            return "".join(out_chars)
        out_chars = []
        cur_w = 0
        limit = max_w - 3
        for ch in text:
            cw = display_width(ch)
            if cur_w + cw > limit:
                break
            out_chars.append(ch)
            cur_w += cw
        return "".join(out_chars).rstrip() + "..."

    def _format_step_banner(self, step_num: int) -> str:
        info = self.step_map.get(step_num)
        if not info:
            return ""
        tag = str(info.get("tag") or "")
        desc = str(info.get("desc") or "").replace("\n", " ").strip()
        prefix = f"[{step_num}/{self.total_steps}]"
        if tag:
            prefix = f"{prefix} [{tag}]"
        max_cols = max(40, _hr_width() - 4)
        avail = max(16, max_cols - len(prefix) - 1)
        if len(desc) > avail:
            desc = desc[: avail - 3] + "..."
        line = f"{prefix} {desc}".rstrip()
        arrow = "▸" if _supports_utf8() else ">"
        if _use_color():
            return f"\x1b[90m{arrow} {line}\x1b[0m\n"
        return f"{arrow} {line}\n"

    def _format_step_done(
        self,
        step_num: int,
        elapsed: float,
        failed: bool = False,
        collapsed: bool = False,
    ) -> str:
        info = self.step_map.get(step_num)
        if info is None:
            return ""
        dur_str = format_duration(elapsed)
        mark = ("✗" if failed else "✓") if _supports_utf8() else ("x" if failed else "+")
        if collapsed:
            tag = str(info.get("tag") or "")
            desc = str(info.get("desc") or "").replace("\n", " ").strip()
            prefix = f"{mark} [{step_num}/{self.total_steps}]"
            if tag:
                prefix = f"{prefix} [{tag}]"
            suffix = f"({dur_str})"
            max_cols = _hr_width()
            if desc:
                avail = max_cols - display_width(prefix) - display_width(suffix) - 2
                if avail >= 4:
                    desc = self._truncate_width(desc, avail)
                    line = f"{prefix} {desc} {suffix}"
                elif avail > 0 and display_width(desc) <= avail:
                    line = f"{prefix} {desc} {suffix}"
                else:
                    line = f"{prefix} {suffix}"
            else:
                line = f"{prefix} {suffix}"
            line = self._truncate_width(line, max_cols)
            ctrl = "\033[1A\r\033[2K"
        else:
            line = f"{mark} [{step_num}/{self.total_steps}] ({dur_str})"
            ctrl = ""
        if _use_color():
            col = "\x1b[31m" if failed else "\x1b[90m"
            return f"{ctrl}{col}{line}\x1b[0m\n"
        return f"{ctrl}{line}\n"

    def _start_step(self, step_num: int) -> str:
        now = float(self._clock())
        parts: list[str] = []
        if self.active_step is not None and self._active_started is not None:
            elapsed = max(0.0, now - self._active_started)
            self.step_durations[self.active_step] = elapsed
            collapsed = self._is_tty and not self._active_has_output
            done_line = self._format_step_done(
                self.active_step, elapsed, collapsed=collapsed
            )
            if done_line:
                parts.append(done_line)
        self.active_step = step_num
        self._active_started = now
        self._active_has_output = False
        if step_num not in self.step_order:
            self.step_order.append(step_num)
        banner = self._format_step_banner(step_num)
        if banner:
            parts.append(banner)
        return "".join(parts)

    def _note_out(self, text: str) -> None:
        if not text:
            return
        if self.active_step is not None:
            self._active_has_output = True
            self._op_text.setdefault(self.active_step, []).append(text)
        else:
            self._pre_text.append(text)
        self._at_line_start = text.endswith("\n")

    def _possible_marker_tail_index(self, s: str) -> int | None:
        idx = s.find(self.marker_prefix)
        if idx != -1:
            return idx
        pfx = self.marker_prefix
        max_k = min(len(pfx) - 1, len(s))
        for k in range(max_k, 0, -1):
            if s.endswith(pfx[:k]):
                return len(s) - k
        return None

    def feed_events(self, text: str) -> list[tuple[str, str]]:
        self.buf += text
        events: list[tuple[str, str]] = []
        while "\n" in self.buf:
            line, rest = self.buf.split("\n", 1)
            self.buf = rest
            m = self._marker_re.match(line)
            if m:
                lead, step_s = m.group(1), m.group(2)
                if lead:
                    self._note_out(lead + "\n")
                    events.append(("out", lead + "\n"))
                elif not self._at_line_start:
                    self._note_out("\n")
                    events.append(("out", "\n"))
                prog = self._start_step(int(step_s))
                if prog:
                    events.append(("prog", prog))
            else:
                self._note_out(line + "\n")
                events.append(("out", line + "\n"))
        if self.buf:
            tail_idx = self._possible_marker_tail_index(self.buf)
            if tail_idx is None:
                self._note_out(self.buf)
                events.append(("out", self.buf))
                self.buf = ""
            elif tail_idx > 0:
                lead_chunk = self.buf[:tail_idx]
                self.buf = self.buf[tail_idx:]
                self._note_out(lead_chunk)
                events.append(("out", lead_chunk))
        return events

    def feed(self, text: str) -> tuple[str, str]:
        out_parts: list[str] = []
        prog_parts: list[str] = []
        for kind, chunk in self.feed_events(text):
            if kind == "prog":
                prog_parts.append(chunk)
            else:
                out_parts.append(chunk)
        return "".join(out_parts), "".join(prog_parts)

    def flush(self, rc: int = 0) -> tuple[str, str]:
        rem_out = ""
        prog_parts: list[str] = []
        if self.buf:
            rem = self.buf
            self.buf = ""
            m = self._marker_re.match(rem)
            if m:
                lead, step_s = m.group(1), m.group(2)
                if lead:
                    self._note_out(lead + "\n")
                    rem_out = lead + "\n"
                elif not self._at_line_start:
                    self._note_out("\n")
                    rem_out = "\n"
                prog = self._start_step(int(step_s))
                if prog:
                    prog_parts.append(prog)
            else:
                self._note_out(rem)
                rem_out = rem
        if self.active_step is not None and self._active_started is not None:
            elapsed = max(0.0, float(self._clock()) - self._active_started)
            self.step_durations[self.active_step] = elapsed
            collapsed = self._is_tty and not self._active_has_output
            done_line = self._format_step_done(
                self.active_step, elapsed, failed=(rc != 0), collapsed=collapsed
            )
            if done_line:
                prog_parts.append(done_line)
            self._active_started = None
        return rem_out, "".join(prog_parts)

    def operation_timings(self, total_chars: int | None = None) -> list[dict[str, object]]:
        raw_pre = "".join(self._pre_text)
        if raw_pre and not raw_pre.endswith("\n"):
            raw_pre += "\n"
        pre = count_tokens(_clean_out_text(raw_pre).encode("utf-8"))
        pos = self.line_base + int(pre["lines"])
        total = int(total_chars or 0)
        timings: list[dict[str, object]] = []
        for step_num in self.step_order:
            if step_num not in self.step_durations:
                continue
            info = self.step_map.get(step_num) or {}
            raw_op = "".join(self._op_text.get(step_num, []))
            if raw_op and not raw_op.endswith("\n"):
                raw_op += "\n"
            text = _clean_out_text(raw_op)
            st = count_tokens(text.encode("utf-8"))
            lines = int(st["lines"])
            chars = int(st["chars"])
            line_no = int(info.get("line") or 0)
            entry: dict[str, object] = {
                "step": step_num,
                "tag": str(info.get("tag") or ""),
                "desc": str(info.get("desc") or "").replace("\n", " ").strip(),
                "duration_ms": int(round(self.step_durations[step_num] * 1000.0)),
                "line": line_no,
                "end_line": int(info.get("end_line") or line_no),
                "lines": lines,
                "chars": chars,
                "bytes": int(st["bytes"]),
                "gpt": int(st["gpt"]),
                "claude": int(st["claude"]),
                "share_pct": round(100.0 * chars / total, 1) if total > 0 else 0.0,
            }
            if lines > 0:
                entry["out_line_start"] = pos + 1
                entry["out_line_end"] = pos + lines
            pos += lines
            timings.append(entry)
        return timings


def _prepare_progress_script(
    script_text: str,
    step_dir: Path,
    step_lines: list[dict[str, object]],
    shell_bin: str,
    work_dir: Path,
) -> Path | None:
    if not step_lines:
        return None
    inst_text = instrument_script_for_progress(script_text, step_lines=step_lines)
    if inst_text == script_text:
        return None
    fd, tmp_name = tempfile.mkstemp(prefix=".progress_", suffix=".sh", dir=step_dir)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(inst_text)
        os.chmod(tmp_path, 0o600)
        chk_cmd = [shell_bin, "-n", str(tmp_path)]
        chk = subprocess.run(
            chk_cmd,
            cwd=work_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if chk.returncode != 0:
            tmp_path.unlink(missing_ok=True)
            return None
        return tmp_path
    except Exception:
        tmp_path.unlink(missing_ok=True)
        return None


def _iter_child_output(fd):
    """Yield decoded chunks read from the single merged child stdout/stderr descriptor."""
    while True:
        try:
            chunk = os.read(fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        yield chunk.decode("utf-8", "replace")


def _script_syntax_context(script_path: Path, msg: str) -> list[str]:
    """Code snippet (+-2 lines) and escaping hints for a shell syntax failure."""
    out: list[str] = []
    m = re.search(r"line (\d+)", msg) or re.search(r"At line:(\d+)", msg)
    try:
        lines = script_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []
    if m and lines:
        lineno = min(max(1, int(m.group(1))), len(lines))
        out.append(f"Context (line {lineno}):")
        for n in range(max(1, lineno - 2), min(len(lines), lineno + 2) + 1):
            mark = ">" if n == lineno else " "
            out.append(f"{mark} {n:>3} | {lines[n - 1]}")
    low = msg.lower()
    if "here-document" in low or "unexpected end of file" in low or "unexpected eof" in low:
        out.append(
            "Hint: check that every heredoc terminator is alone at column 0, quotes are balanced, "
            "and no triple backticks or paired dollar signs appear inside the block"
        )
    return out


def _validate_step_script_syntax(
    label: str,
    script_path: Path,
    out_path: Path,
    work_dir: Path,
    shell_bin: str,
    sdir: Path,
    headless: bool = False,
    footer_on_fail: str | None = None,
    renumbered_from: str | None = None,
    reasoning: str | None = None,
    protocol_notes: list[str] | None = None,
    reply_transport: str | None = None,
    protocol_violations: dict[str, object] | None = None,
) -> int:
    chk_cmd = [shell_bin, "-n", str(script_path)]
    chk = subprocess.run(
        chk_cmd,
        cwd=work_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if chk.returncode == 0:
        return 0
    renum_note = (
        f"[{label}] Note: renumbered from {renumbered_from} to {label}; continue from {label}.\n"
        if renumbered_from else ""
    )
    extra_notes = "".join(n if n.endswith("\n") else n + "\n" for n in (protocol_notes or []))
    start_line = f"[{label}] START\n{renum_note}{extra_notes}\n"
    msg = chk.stdout or "syntax check failed\n"
    ctx_lines = _script_syntax_context(script_path, msg)
    if ctx_lines:
        msg = msg if msg.endswith("\n") else msg + "\n"
        msg += "\n".join(ctx_lines) + "\n"
    end_line = f"[{label}] END (syntax error, exit {chk.returncode})\n"
    if footer_on_fail:
        end_line += footer_on_fail if footer_on_fail.endswith("\n") else footer_on_fail + "\n"
    full_output = start_line + msg + end_line
    write_private(out_path, full_output, overwrite=True)
    write_step_meta(
        script_path.parent,
        duration_ms=0,
        exit_code=chk.returncode,
        outcome="syntax-error",
        reason=(msg.strip().splitlines() or [""])[0] or None,
        renumbered_from=renumbered_from,
        reasoning=reasoning,
        reply_transport=reply_transport,
        protocol_violations=protocol_violations,
    )
    if headless:
        sys.stdout.write(full_output)
        sys.stdout.flush()
        return chk.returncode
    err_lines = msg.rstrip("\n").splitlines() or ["syntax check failed"]
    box_lines = [
        f"Exit: {chk.returncode}",
        f"Script: {script_path}",
        f"Output: {out_path}",
        f"Error: {err_lines[0]}",
        *(f"  {eline}" for eline in err_lines[1:]),
    ]
    can_prompt_clip = (
        not in_run_block()
        and sys.stdout.isatty()
        and clipboard_mode() == "prompt"
        and clipboard_command(out_path) is not None
    )
    if can_prompt_clip:
        offer_clipboard_copy(label, out_path, rc=chk.returncode, title_kind="SYNTAX ERROR", extra_lines=box_lines, sdir=sdir)
    else:
        full_body = build_box_body_lines(
            out_path, rc=chk.returncode, stats=stats_line(out_path), extra_lines=box_lines, label=label, sdir=sdir
        )
        sys.stdout.write(format_info_box("SYNTAX ERROR", full_body) + "\n")
        sys.stdout.flush()
        if not in_run_block():
            offer_clipboard_copy(label, out_path, rc=chk.returncode, title_kind="SYNTAX ERROR", extra_lines=box_lines, sdir=sdir)
    return chk.returncode


def _persist_step_reasoning(step_dir: Path, reasoning: str | None) -> str | None:
    clean = (reasoning or "").strip()
    if not clean:
        return None
    step_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    write_private(step_dir / "plan.md", clean + "\n", overwrite=True)
    return clean


def run_script(
    label: str,
    script_path: Path,
    out_path: Path,
    header_lines: list[str] | None = None,
    auto_yes: bool = False,
    sandbox_override: str | None = None,
    footer_on_fail: str | None = None,
    renumbered_from: str | None = None,
    reasoning: str | None = None,
    protocol_notes: list[str] | None = None,
    reply_transport: str | None = None,
    protocol_violations: dict[str, object] | None = None,
) -> int:
    headless = os.environ.get("RUN_BLOCK_HEADLESS") == "1"
    step_dir = script_path.parent
    sdir = step_dir.parent
    clean_reasoning = _persist_step_reasoning(step_dir, reasoning) or _resolve_step_reasoning(step_dir=step_dir) or None
    work_dir = get_work_dir(sdir)
    sandbox_mode = get_sandbox_mode(sdir, override=sandbox_override)
    shell_bin, _ = get_setting("shell")
    script_text = script_path.read_text(encoding="utf-8")
    exec_cmd = [shell_bin, str(script_path)]

    rc_syn = _validate_step_script_syntax(
        label,
        script_path,
        out_path,
        work_dir,
        shell_bin,
        sdir,
        headless=headless,
        footer_on_fail=footer_on_fail,
        renumbered_from=renumbered_from,
        reasoning=clean_reasoning,
        protocol_notes=protocol_notes,
        reply_transport=reply_transport,
        protocol_violations=protocol_violations,
    )
    if rc_syn != 0:
        return rc_syn

    aborted_marker = step_dir / "aborted"
    summary_obj = summarize_script_actions(script_text, work_dir=work_dir)
    summary_obj["sandbox"] = sandbox_mode
    if clean_reasoning:
        summary_obj["reasoning"] = clean_reasoning
    approved, abort_reason = confirm_execution(
        label, script_text, summary=summary_obj, script_path=script_path, auto_yes=(auto_yes or headless)
    )
    if not approved:
        write_private(aborted_marker, "aborted\n", overwrite=True)
        user_aborted = abort_reason == "USER_ABORTED"
        reason_str = abort_reason or f"aborted by user (re-run with: {prog_name()} --retry {label})"
        write_step_meta(
            step_dir,
            duration_ms=0,
            exit_code=130,
            outcome="aborted",
            reason=None if user_aborted else reason_str,
            renumbered_from=renumbered_from,
            reasoning=clean_reasoning,
            reply_transport=reply_transport,
            protocol_violations=protocol_violations,
        )
        if user_aborted:
            return 130
        return not_run_exit(
            label, sdir, step_dir.name, out_path, f"[{label}] NOT RUN: {reason_str}", rc=130, headless=headless,
            outcome=None,
        )
    aborted_marker.unlink(missing_ok=True)

    if script_path.is_file():
        updated_text = script_path.read_text(encoding="utf-8")
        if updated_text != script_text:
            script_text = updated_text
            rc_syn = _validate_step_script_syntax(
                label,
                script_path,
                out_path,
                work_dir,
                shell_bin,
                sdir,
                headless=headless,
                footer_on_fail=footer_on_fail,
                renumbered_from=renumbered_from,
                reasoning=clean_reasoning,
                protocol_notes=protocol_notes,
                reply_transport=reply_transport,
                protocol_violations=protocol_violations,
            )
            if rc_syn != 0:
                return rc_syn
            summary_obj = summarize_script_actions(script_text, work_dir=work_dir)
            summary_obj["sandbox"] = sandbox_mode
            if clean_reasoning:
                summary_obj["reasoning"] = clean_reasoning

    start_line = f"[{label}] START\n"
    log_chunks: list[str] = [start_line]
    if renumbered_from:
        log_chunks.append(f"[{label}] Note: renumbered from {renumbered_from} to {label}; continue from {label}.\n")
    for note_ln in protocol_notes or []:
        log_chunks.append(note_ln if note_ln.endswith("\n") else note_ln + "\n")

    def _emit(text: str) -> None:
        if progress_filter is not None:
            events = progress_filter.feed_events(text)
            for kind, chunk in events:
                if kind == "out":
                    log_chunks.append(chunk)
                sys.stdout.write(chunk)
            if events:
                sys.stdout.flush()
        else:
            log_chunks.append(text)
            sys.stdout.write(text)
            sys.stdout.flush()
    for h in header_lines or []:
        log_chunks.append(h)
    log_chunks.append("\n")
    if headless:
        sys.stdout.write("".join(log_chunks))
    elif header_lines:
        sys.stdout.write("".join(header_lines) + "\n")
    sys.stdout.flush()

    tty_in = None
    master_fd = None
    slave_fd = None
    if HAS_PTY and sys.stdout.isatty() and not no_clipboard() and not headless:
        try:
            tty_in = open("/dev/tty", "rb", buffering=0)
            master_fd, slave_fd = pty.openpty()
            attrs = termios.tcgetattr(slave_fd)
            attrs[1] &= ~termios.ONLCR
            termios.tcsetattr(slave_fd, termios.TCSANOW, attrs)
        except OSError:
            if tty_in is not None:
                tty_in.close()
                tty_in = None
            if master_fd is not None:
                os.close(master_fd)
                master_fd = None
            if slave_fd is not None:
                os.close(slave_fd)
                slave_fd = None

    step_lines = list(summary_obj.get("operation_steps") or [])
    use_progress = (
        not headless
        and not in_run_block()
        and sys.stdout.isatty()
        and get_setting("progress")[0] != "false"
        and bool(step_lines)
    )
    tmp_progress_path: Path | None = None
    progress_filter: _ProgressLineFilter | None = None
    if use_progress:
        tmp_progress_path = _prepare_progress_script(
            script_text, step_dir, step_lines, shell_bin, work_dir
        )
        if tmp_progress_path is not None:
            step_map = {int(s["step"]): s for s in step_lines if s.get("step")}
            progress_filter = _ProgressLineFilter(step_map, len(step_lines))
            progress_filter.line_base = sum(c.count("\n") for c in log_chunks)
            exec_cmd = [shell_bin, str(tmp_progress_path)]

    bundle_file = sdir / "0"
    bundle_snapshot = bundle_file.read_bytes() if bundle_file.is_file() else None
    pager_cmd, _ = get_setting("pager")
    pager_env = {k: pager_cmd for k in CHILD_PAGER_ENV_VARS} if pager_cmd else {}
    child_env = scrub_child_env(
        {
            **os.environ,
            **pager_env,
            "IN_RUN_BLOCK": "1",
            "RUN_BLOCK_PARENT_SESSION": sdir.name,
            "RUN_BLOCK_PARENT_STEP": step_dir.name,
        },
        sandbox_mode,
    )
    exec_cmd = build_sandbox_exec(exec_cmd, work_dir=work_dir, base_dir=ensure_base(), sandbox_mode=sandbox_mode)
    exec_started = time.monotonic()
    try:
        if master_fd is not None and slave_fd is not None:
            try:
                proc = subprocess.Popen(
                    exec_cmd,
                    cwd=work_dir,
                    stdin=tty_in if tty_in is not None else slave_fd,
                    stdout=slave_fd,
                    stderr=slave_fd,
                    env=child_env,
                    close_fds=True,
                )
                os.close(slave_fd)
                slave_fd = None
                for text in _iter_child_output(master_fd):
                    _emit(text)
                rc = proc.wait()
            finally:
                if slave_fd is not None:
                    os.close(slave_fd)
                if master_fd is not None:
                    os.close(master_fd)
                if tty_in is not None:
                    tty_in.close()
        else:
            out_r, out_w = os.pipe()
            try:
                proc = subprocess.Popen(
                    exec_cmd,
                    cwd=work_dir,
                    stdin=subprocess.DEVNULL,
                    stdout=out_w,
                    stderr=out_w,
                    env=child_env,
                )
            except BaseException:
                os.close(out_r)
                raise
            finally:
                os.close(out_w)
            try:
                for text in _iter_child_output(out_r):
                    _emit(text)
            finally:
                os.close(out_r)
            rc = proc.wait()
        duration_s = max(0.0, time.monotonic() - exec_started)
        if progress_filter is not None:
            rem_out, rem_prog = progress_filter.flush(rc=rc)
            if rem_out:
                log_chunks.append(rem_out)
                sys.stdout.write(rem_out)
                if not rem_out.endswith("\n"):
                    log_chunks.append("\n")
                    sys.stdout.write("\n")
            if rem_prog:
                sys.stdout.write(rem_prog)
            if rem_out or rem_prog:
                sys.stdout.flush()
    finally:
        if tmp_progress_path is not None:
            tmp_progress_path.unlink(missing_ok=True)
    if bundle_snapshot is not None:
        if not bundle_file.is_file() or bundle_file.read_bytes() != bundle_snapshot:
            write_private(bundle_file, bundle_snapshot.decode("utf-8", "replace"), overwrite=True)
            warn_msg = f"\n[{label}] SECURITY WARNING: block attempted to modify {bundle_file.name} (reverted)\n"
            log_chunks.append(warn_msg)
            sys.stdout.write(warn_msg)
            sys.stdout.flush()
    if log_chunks and not log_chunks[-1].endswith("\n"):
        log_chunks.append("\n")
        sys.stdout.write("\n")
    pre_child_count = 1 + (1 if renumbered_from else 0) + len(protocol_notes or []) + len(header_lines or []) + 1
    captured_child_text = _clean_out_text("".join(log_chunks[pre_child_count:]))
    post_child_chunks: list[str] = []
    stdin_diag_lines: list[str] = []
    if rc != 0:
        stdin_diag_lines = _resolve_python_stdin_tracebacks(label, script_text, captured_child_text)
        for diag in stdin_diag_lines:
            post_child_chunks.append(diag + "\n")
    pi_warn_line = _detect_output_prompt_injection_warning(label, captured_child_text)
    if pi_warn_line:
        post_child_chunks.append(pi_warn_line)
    dur_str = format_duration(duration_s)
    duration_ms = int(round(duration_s * 1000.0))
    failed_step = (
        progress_filter.active_step
        if (rc != 0 and progress_filter is not None)
        else None
    )
    end_detail = f"exit {rc}, {dur_str}" if rc != 0 else dur_str
    end_line = f"\n[{label}] END ({end_detail})\n"
    if rc != 0 and footer_on_fail:
        end_line += footer_on_fail if footer_on_fail.endswith("\n") else footer_on_fail + "\n"
    post_child_chunks.append(end_line)
    full_output = "".join(log_chunks[:pre_child_count]) + captured_child_text + "".join(post_child_chunks)
    op_timings = (
        progress_filter.operation_timings(total_chars=len(full_output))
        if progress_filter is not None
        else []
    )
    write_step_meta(
        step_dir,
        duration_ms=duration_ms,
        exit_code=rc,
        operations=op_timings,
        failed_step=failed_step,
        renumbered_from=renumbered_from,
        reasoning=clean_reasoning,
        reply_transport=reply_transport,
        protocol_violations=protocol_violations,
        prompt_injection_warning=bool(pi_warn_line),
    )
    write_private(out_path, full_output)
    try:
        update_session_stats(
            sdir,
            ok=(rc == 0),
            duration_s=float(duration_s or 0.0),
            is_fix="_" in step_dir.name,
            renumbered=bool(renumbered_from),
        )
    except OSError:
        pass
    deferred_cards = pop_deferred_cards(step_dir)
    end_session_cards = [c for c in deferred_cards if c.get("kind") == "end_session"]
    clip_target = resolve_clipboard_target(out_path, full_output)
    if headless:
        if stdin_diag_lines:
            sys.stdout.write("".join(d + "\n" for d in stdin_diag_lines))
        if pi_warn_line:
            sys.stdout.write(pi_warn_line)
        sys.stdout.write(end_line)
        sys.stdout.flush()
    elif (
        in_run_block()
        or not sys.stdout.isatty()
        or clipboard_mode() != "prompt"
        or clipboard_command(clip_target) is None
    ):
        end_body = build_box_body_lines(
            clip_target,
            rc=rc,
            stats=stats_line(clip_target),
            label=label,
            sdir=sdir,
            duration_s=duration_s,
            op_timings=op_timings,
            failed_step=failed_step,
        )
        sys.stdout.write("\n" + format_info_box("END STEP", end_body) + "\n")
        sys.stdout.flush()
    if not headless:
        offer_clipboard_copy(
            label,
            out_path,
            rc=rc,
            duration_s=duration_s,
            op_timings=op_timings,
            failed_step=failed_step,
            sdir=sdir,
        )
    base_dir = sdir.parent
    for card in end_session_cards:
        sess_name = str(card.get("session") or sdir.name)
        target_sdir = base_dir / sess_name
        if target_sdir.is_dir():
            render_end_session_card(target_sdir, headless=headless)
    return rc


def _guard_completed_session(
    label: str,
    sdir: Path,
    step_name: str,
    out_path: Path,
    headless: bool,
    fix_target: str | None = None,
    auto_yes: bool = False,
) -> int | None:
    if not is_session_completed(sdir):
        return None
    session = sdir.name
    if auto_yes or headless:
        clear_session_completed(sdir)
        return None
    rc = 2
    reason = f"session {session} is marked as completed (pass -y/--yes to reopen and run)"
    if sys.stdout.isatty():
        meta = read_session_meta(sdir)
        def _completed_lines() -> list[str]:
            hdr = format_session_header_lines(label=label, sdir=sdir)
            comp_lines = [f"Completed: {meta.get('completed_at') or 'unknown'}"]
            if meta.get("completed_note"):
                comp_lines.append(f"Note: {meta['completed_note']}")
            return [*hdr, "", *comp_lines]

        choice = prompt_yes_no_box(
            "SESSION COMPLETED",
            _completed_lines(),
            f"-> Reopen session {session}?",
            default_yes=False,
            yes_status="✓ Session reopened.",
            no_status="✗ Session stays completed.",
            content_builder=_completed_lines,
            label=label,
            sdir=sdir,
        )
        if choice is True:
            clear_session_completed(sdir)
            return None
        rc = 130
        reason = f"session {session} is marked as completed (not reopened)"
    step_dir = _step_dir(sdir, step_name)
    existed = step_dir.exists()
    rc_out = not_run_exit(
        label, sdir, step_name, out_path, f"[{label}] NOT RUN: {reason}", rc=rc, headless=headless, fix_target=fix_target
    )
    if not existed:
        shutil.rmtree(step_dir, ignore_errors=True)
    return rc_out


def _reject_nested_step_execution(action: str) -> int:
    prog = prog_name()
    parent_ref = parent_run_block_ref()
    where = f" (active step: {parent_ref[0]}/{parent_ref[1]})" if parent_ref else ""
    sys.stderr.write(
        f"{prog}: cannot run {action} from inside a running block{where}\n"
    )
    sys.stderr.flush()
    return 2


def _merge_protocol_violation_dicts(
    primary: dict[str, object] | None,
    secondary: dict[str, object] | None,
) -> dict[str, object] | None:
    if not primary and not secondary:
        return None
    p = dict(primary or {})
    s = dict(secondary or {})
    merged: dict[str, object] = {
        "ignored_trailing_blocks": int(p.get("ignored_trailing_blocks") or 0)
        + int(s.get("ignored_trailing_blocks") or 0),
        "ignored_trailing_refs": list(p.get("ignored_trailing_refs") or [])
        + list(s.get("ignored_trailing_refs") or []),
        "duplicate_count": int(p.get("duplicate_count") or 0) + int(s.get("duplicate_count") or 0),
        "glued_fence": bool(p.get("glued_fence") or s.get("glued_fence")),
        "trailing_prose": "\n".join(
            t for t in (
                str(p.get("trailing_prose") or "").strip(),
                str(s.get("trailing_prose") or "").strip(),
            ) if t
        ),
        "repaired": bool(p.get("repaired") or s.get("repaired")),
        "had_wrapper": bool(p.get("had_wrapper") or s.get("had_wrapper")),
        "wrapped_tool_script": bool(p.get("wrapped_tool_script") or s.get("wrapped_tool_script")),
    }
    return merged


def cmd_normal(
    ref: str,
    payload: str,
    auto_yes: bool = False,
    sandbox_override: str | None = None,
    *,
    reasoning: str | None = None,
    renumbered_from: str | None = None,
    reply_transport: str | None = None,
    protocol_violations: dict[str, object] | None = None,
) -> int:
    if in_run_block():
        return _reject_nested_step_execution(f"block {ref}")
    payload, split_err, split_meta = _reassemble_split_payload_with_meta(payload)
    merged_violations = _merge_protocol_violation_dicts(protocol_violations, split_meta)
    headless = os.environ.get("RUN_BLOCK_HEADLESS") == "1"
    session, step = parse_ref(ref, allow_fix_step=False)
    step_num = int(step)
    if step_num < 1:
        raise SystemExit(f"{prog_name()}: step number must be >= 1")
    base = ensure_base()
    _warn_if_state_oversized(base)
    sdir = base / session
    sdir.mkdir(mode=0o700, parents=True, exist_ok=True)
    ensure_session_bundle(sdir, sandbox_mode=sandbox_override)
    label = f"{session}/{step}"
    step_dir = _step_dir(sdir, step)
    script_path = _find_step_script(sdir, step)
    out_path = step_dir / "out"
    if split_err:
        return not_run_exit(label, sdir, step, out_path, f"[{label}] NOT RUN: {split_err}", headless=headless)
    rc_done = _guard_completed_session(label, sdir, step, out_path, headless, auto_yes=auto_yes)
    if rc_done is not None:
        return rc_done

    aborted_marker = step_dir / "aborted"

    overwrite = aborted_marker.exists()
    if overwrite:
        out_path.unlink(missing_ok=True)
        (step_dir / "meta.json").unlink(missing_ok=True)
        aborted_marker.unlink(missing_ok=True)
        for orig_p in (step_dir / "block.orig.sh", step_dir / "out.orig"):
            orig_p.unlink(missing_ok=True)
    elif script_path.exists() or out_path.exists():
        if sys.stdout.isatty() and not no_clipboard() and not headless:
            next_num = next_free_step(sdir, min_step=step_num + 1)
            next_label = f"{session}/{next_num}"
            existing_lines = [f"Next: {next_label}"]
            if script_path.exists():
                existing_lines.append(f"Script: {script_path}")
            if out_path.exists():
                existing_lines.append(f"Output: {out_path}")
            def _step_exists_lines() -> list[str]:
                hdr = format_session_header_lines(
                    label=label, sdir=sdir, sandbox_mode=sandbox_override
                )
                return [*hdr, "", *existing_lines]

            if out_path.exists():
                choice = prompt_yes_no_box(
                    "STEP ALREADY EXISTS",
                    _step_exists_lines(),
                    "Copy out to clipboard?",
                    default_yes=True,
                    no_status=f"✗ Keeping existing {label}.",
                    script_path=script_path if script_path.exists() else None,
                    out_path=out_path,
                    renumber_label=next_label,
                    renumber_status=f"✓ Renumbering {label} -> {next_label}.",
                    content_builder=_step_exists_lines,
                    copy_on_yes=True,
                    label=label,
                    sdir=sdir,
                    sandbox_mode=sandbox_override,
                    allow_overwrite=True,
                )
            else:
                choice = prompt_yes_no_box(
                    "STEP ALREADY EXISTS",
                    _step_exists_lines(),
                    f"Renumber to {next_label}?",
                    default_yes=False,
                    no_status=f"✗ Keeping existing {label}.",
                    script_path=script_path if script_path.exists() else None,
                    renumber_label=next_label,
                    renumber_status=f"✓ Renumbering {label} -> {next_label}.",
                    content_builder=_step_exists_lines,
                    renumber_only=True,
                    label=label,
                    sdir=sdir,
                    sandbox_mode=sandbox_override,
                    allow_overwrite=True,
                )
            if choice == "renumber":
                renumbered_from = label
                payload = _rewrite_script_step_header(payload, label, next_label)
                step = str(next_num)
                step_num = next_num
                label = next_label
                step_dir = _step_dir(sdir, step)
                script_path = _find_step_script(sdir, step)
                out_path = step_dir / "out"
                aborted_marker = step_dir / "aborted"
                overwrite = False
            elif choice == "overwrite":
                out_path.unlink(missing_ok=True)
                (step_dir / "meta.json").unlink(missing_ok=True)
                (step_dir / "error").unlink(missing_ok=True)
                aborted_marker.unlink(missing_ok=True)
                for orig_p in (step_dir / "block.orig.sh", step_dir / "out.orig"):
                    orig_p.unlink(missing_ok=True)
                overwrite = True
            elif choice == "copy":
                return 0
            else:
                return 2
        if not overwrite and renumbered_from is None:
            return not_run_exit(label, sdir, step, out_path, f"[{label}] NOT RUN: step already exists — output: {out_path}", headless=headless)
    if step_num > 1 and renumbered_from is None and not _find_step_script(sdir, str(step_num - 1)).exists():
        prev_label = f"{session}/{step_num - 1}"
        if sys.stdout.isatty() and not no_clipboard() and not headless:
            first_missing_num = first_missing_step(sdir)
            first_missing_label = f"{session}/{first_missing_num}"
            def _missing_prev_lines() -> list[str]:
                hdr = format_session_header_lines(
                    label=label, sdir=sdir, sandbox_mode=sandbox_override
                )
                lines = [*hdr, "", f"Missing: {prev_label}"]
                if first_missing_label != prev_label:
                    lines.append(f"Next: {first_missing_label}")
                return lines

            choice = prompt_yes_no_box(
                "MISSING PREVIOUS STEP",
                _missing_prev_lines(),
                f"Renumber to {first_missing_label}?",
                default_yes=False,
                no_status=f"✗ Canceled {label} (run {prev_label} first).",
                renumber_label=first_missing_label,
                renumber_status=f"✓ Renumbering {label} -> {first_missing_label}.",
                content_builder=_missing_prev_lines,
                renumber_only=True,
                label=label,
                sdir=sdir,
                sandbox_mode=sandbox_override,
            )
            if choice == "renumber":
                renumbered_from = label
                payload = _rewrite_script_step_header(payload, label, first_missing_label)
                step = str(first_missing_num)
                step_num = first_missing_num
                label = first_missing_label
                step_dir = _step_dir(sdir, step)
                script_path = _find_step_script(sdir, step)
                out_path = step_dir / "out"
                aborted_marker = step_dir / "aborted"
                overwrite = aborted_marker.exists()
                if overwrite:
                    out_path.unlink(missing_ok=True)
                    (step_dir / "meta.json").unlink(missing_ok=True)
                    aborted_marker.unlink(missing_ok=True)
                    for orig_p in (step_dir / "block.orig.sh", step_dir / "out.orig"):
                        orig_p.unlink(missing_ok=True)
            else:
                return 2
        if renumbered_from is None:
            return not_run_exit(
                label,
                sdir,
                step,
                out_path,
                f"[{label}] NOT RUN: previous step {prev_label} has not been run yet",
                headless=headless,
            )
    if not payload.strip():
        return not_run_exit(label, sdir, step, out_path, f"[{label}] NOT RUN: empty script on stdin", headless=headless)

    protocol_notes, recorded_violations = format_protocol_reminder_lines(
        label,
        reply_transport=reply_transport or "text",
        protocol_violations=merged_violations,
    )
    step_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    _persist_step_reasoning(step_dir, reasoning)
    write_private(script_path, payload, overwrite=overwrite)
    return run_script(
        label,
        script_path,
        out_path,
        auto_yes=auto_yes,
        sandbox_override=sandbox_override,
        renumbered_from=renumbered_from,
        reasoning=reasoning,
        protocol_notes=protocol_notes,
        reply_transport=reply_transport,
        protocol_violations=recorded_violations,
    )


def cmd_retry(
    ref: str | None = None, auto_yes: bool = False, sandbox_override: str | None = None
) -> int:
    if in_run_block():
        target = f"--retry {ref}" if ref else "--retry"
        return _reject_nested_step_execution(target)
    if ref and "/" not in ref:
        session, step = _find_latest_step(ref)
    elif ref:
        session, step = parse_ref(ref, allow_fix_step=True)
    else:
        session, step = _find_latest_step()
    sdir = ensure_base() / session
    step_dir = _step_dir(sdir, step)
    script_path = _find_step_script(sdir, step)
    out_path = step_dir / "out"
    if not script_path.is_file():
        raise SystemExit(f"{prog_name()}: block {session}/{step} not found ({script_path})")
    rc_done = _guard_completed_session(
        f"{session}/{step}",
        sdir,
        step,
        out_path,
        os.environ.get("RUN_BLOCK_HEADLESS") == "1",
        auto_yes=auto_yes,
    )
    if rc_done is not None:
        return rc_done
    out_path.unlink(missing_ok=True)
    (step_dir / "out.orig").unlink(missing_ok=True)
    (step_dir / "meta.json").unlink(missing_ok=True)
    (step_dir / "error").unlink(missing_ok=True)
    (step_dir / "aborted").unlink(missing_ok=True)
    return run_script(
        f"{session}/{step}",
        script_path,
        out_path,
        auto_yes=auto_yes,
        sandbox_override=sandbox_override,
    )

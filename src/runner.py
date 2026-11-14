def ensure_base() -> Path:
    BASE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        BASE_DIR.chmod(0o700)
    except OSError:
        pass
    return BASE_DIR


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
    if not name:
        name = next_session_name(base)
    if not re.fullmatch(r"[A-Za-z0-9._-]+", name):
        raise SystemExit(f"{prog_name()}: invalid session name: {name!r}")
    sdir = base / name
    if sdir.exists():
        if not force:
            if not sys.stdin.isatty():
                raise SystemExit(f"{prog_name()}: session {sdir} already exists (use --force to overwrite)")
            if sys.stdout.isatty() and not no_clipboard():
                sess_hdr = format_session_header_lines(
                    label=name, sdir=sdir, sandbox_mode=sandbox_mode
                )
                ok = prompt_yes_no_box(
                    "SESSION ALREADY EXISTS",
                    [*sess_hdr, "", f"Directory: {sdir}"],
                    f"Overwrite session {name}?",
                    default_yes=False,
                    yes_status=f"✓ Overwriting session {name}.",
                    no_status=f"✗ Aborted overwriting session {name}.",
                )
                if not ok:
                    raise SystemExit(f"{prog_name()}: aborted")
            else:
                sys.stderr.write(f"Session {sdir} already exists. Overwrite? [y/N] ")
                sys.stderr.flush()
                ans = sys.stdin.readline().strip().lower()
                if ans not in ("y", "yes"):
                    raise SystemExit(f"{prog_name()}: aborted")
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


def next_fix_step(step: str) -> str:
    if "_" in step:
        base, sub = step.split("_", 1)
        return f"{base}_{int(sub) + 1}"
    return f"{step}_1"


def write_private(path: Path, content: str, overwrite: bool = False) -> None:
    flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if overwrite else os.O_EXCL)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)


def not_run_exit(
    label: str, sdir: Path, step_name: str, out_path: Path, msg: str, rc: int = 2, headless: bool = False
) -> int:
    sdir.mkdir(mode=0o700, parents=True, exist_ok=True)
    line = msg if msg.endswith("\n") else msg + "\n"
    clean_msg = msg.strip()
    prefix = f"[{label}] NOT RUN:"
    detail = clean_msg[len(prefix):].strip() if clean_msg.startswith(prefix) else clean_msg
    err_target = sdir / f"{step_name}.error.txt" if out_path.exists() else out_path
    try:
        write_private(err_target, line, overwrite=True)
    except Exception:
        pass
    is_headless = headless or os.environ.get("RUN_BLOCK_HEADLESS") == "1"
    if is_headless:
        sys.stdout.write(line)
        sys.stdout.flush()
        return rc
    body_lines = [
        f"Reason: {detail}",
        f"Output: {err_target}",
    ]
    can_prompt_clip = (
        not in_run_block()
        and sys.stdout.isatty()
        and clipboard_mode() == "prompt"
        and clipboard_command(err_target) is not None
    )
    if can_prompt_clip:
        offer_clipboard_copy(label, err_target, ok=False, rc=rc, title_kind="NOT RUN", extra_lines=body_lines)
    else:
        full_body = build_box_body_lines(
            err_target, rc=rc, stats=stats_line(err_target), extra_lines=body_lines, label=label, sdir=sdir
        )
        sys.stdout.write(format_info_box("NOT RUN", full_body) + "\n")
        sys.stdout.flush()
        if not in_run_block():
            offer_clipboard_copy(label, err_target, ok=False, rc=rc, title_kind="NOT RUN", extra_lines=body_lines)
    return rc


def run_script(
    label: str,
    script_path: Path,
    out_path: Path,
    header_lines: list[str] | None = None,
    cleanup_on_abort: list[Path] | None = None,
    auto_yes: bool = False,
    sandbox_override: str | None = None,
) -> int:
    headless = auto_yes or os.environ.get("RUN_BLOCK_HEADLESS") == "1"
    sdir = script_path.parent
    work_dir = get_work_dir(sdir)
    sandbox_mode = get_sandbox_mode(sdir, override=sandbox_override)
    shell_bin, _ = get_setting("shell")
    is_ps = _is_powershell(shell_bin)
    script_text = script_path.read_text(encoding="utf-8")

    if is_ps:
        ps_check = (
            "$err = $null; "
            "[void][System.Management.Automation.Language.Parser]::ParseFile($args[0], [ref]$null, [ref]$err); "
            "if ($err) { foreach ($e in $err) { [Console]::Error.WriteLine($e.ToString()) }; exit 1 }"
        )
        chk_cmd = [shell_bin, "-NoProfile", "-NonInteractive", "-Command", ps_check, str(script_path)]
        exec_cmd = [shell_bin, "-NoProfile", "-File", str(script_path)]
    else:
        chk_cmd = [shell_bin, "-n", str(script_path)]
        exec_cmd = [shell_bin, str(script_path)]

    chk = subprocess.run(
        chk_cmd,
        cwd=work_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if chk.returncode != 0:
        start_line = f"[{label}] START\n\n"
        msg = chk.stdout or "syntax check failed\n"
        end_line = f"[{label}] END (syntax error, exit {chk.returncode})\n"
        full_output = start_line + msg + end_line
        write_private(out_path, full_output)
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
            offer_clipboard_copy(label, out_path, ok=False, rc=chk.returncode, title_kind="SYNTAX ERROR", extra_lines=box_lines)
        else:
            full_body = build_box_body_lines(
                out_path, rc=chk.returncode, stats=stats_line(out_path), extra_lines=box_lines, label=label, sdir=sdir
            )
            sys.stdout.write(format_info_box("SYNTAX ERROR", full_body) + "\n")
            sys.stdout.flush()
            if not in_run_block():
                offer_clipboard_copy(label, out_path, ok=False, rc=chk.returncode, title_kind="SYNTAX ERROR", extra_lines=box_lines)
        return chk.returncode

    aborted_marker = script_path.with_suffix(".aborted")
    summary_obj = summarize_script_actions(script_text, work_dir=work_dir)
    summary_obj["sandbox"] = sandbox_mode
    approved, abort_reason = confirm_execution(
        label, script_text, summary=summary_obj, script_path=script_path, auto_yes=headless
    )
    if not approved:
        write_private(aborted_marker, "aborted\n", overwrite=True)
        if abort_reason == "USER_ABORTED":
            return 130
        reason_str = abort_reason or f"aborted by user (re-run with: {prog_name()} --retry {label})"
        return not_run_exit(
            label, script_path.parent, script_path.stem, out_path, f"[{label}] NOT RUN: {reason_str}", rc=130, headless=headless
        )
    aborted_marker.unlink(missing_ok=True)

    start_line = f"[{label}] START\n"
    log_chunks: list[str] = [start_line]
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

    bundle_file = sdir / "0.txt"
    bundle_snapshot = bundle_file.read_bytes() if bundle_file.is_file() else None
    child_env = scrub_child_env({**os.environ, "IN_RUN_BLOCK": "1"}, sandbox_mode)
    exec_cmd = build_sandbox_exec(exec_cmd, work_dir=work_dir, base_dir=ensure_base(), sandbox_mode=sandbox_mode)
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
            while True:
                try:
                    chunk = os.read(master_fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                text = chunk.decode("utf-8", "replace")
                log_chunks.append(text)
                sys.stdout.write(text)
                sys.stdout.flush()
            rc = proc.wait()
        finally:
            if slave_fd is not None:
                os.close(slave_fd)
            if master_fd is not None:
                os.close(master_fd)
            if tty_in is not None:
                tty_in.close()
    else:
        proc = subprocess.Popen(
            exec_cmd,
            cwd=work_dir,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=child_env,
        )
        assert proc.stdout is not None
        while True:
            chunk = proc.stdout.read1(4096) if hasattr(proc.stdout, "read1") else proc.stdout.read(4096)
            if not chunk:
                break
            text = chunk.decode("utf-8", "replace")
            log_chunks.append(text)
            sys.stdout.write(text)
            sys.stdout.flush()
        proc.stdout.close()
        rc = proc.wait()
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
    exit_str = f" (exit {rc})" if rc != 0 else ""
    end_line = f"\n[{label}] END{exit_str}\n"
    log_chunks.append(end_line)
    full_output = CR_LINE_RE.sub("", ANSI_RE.sub("", "".join(log_chunks))).replace("\r\n", "\n")
    write_private(out_path, full_output)
    clip_target = resolve_clipboard_target(out_path, full_output)
    if headless:
        sys.stdout.write(end_line)
        sys.stdout.flush()
    elif in_run_block() or not sys.stdout.isatty() or clipboard_mode() != "prompt" or clipboard_command(clip_target) is None:
        end_body = build_box_body_lines(clip_target, rc=rc, stats=stats_line(clip_target), label=label, sdir=sdir)
        sys.stdout.write("\n" + format_info_box("END", end_body) + "\n")
        sys.stdout.flush()
    if not headless:
        offer_clipboard_copy(label, clip_target, ok=(rc == 0), rc=rc)
    return rc


TRAILING_FENCE_RE = re.compile(r"(?:\r?\n)+(?:RUN_(?:BLOCK|FIX)\s*)?`{3,}\s*$")


def _strip_trailing_fence(payload: str) -> str:
    cleaned = TRAILING_FENCE_RE.sub("", payload)
    return (cleaned + "\n") if cleaned and not cleaned.endswith("\n") else cleaned


def cmd_normal(
    ref: str, payload: str, auto_yes: bool = False, sandbox_override: str | None = None
) -> int:
    payload = _strip_trailing_fence(payload)
    headless = auto_yes or os.environ.get("RUN_BLOCK_HEADLESS") == "1"
    session, step = parse_ref(ref, allow_fix_step=False)
    step_num = int(step)
    if step_num < 1:
        raise SystemExit(f"{prog_name()}: step number must be >= 1")
    sdir = ensure_base() / session
    sdir.mkdir(mode=0o700, parents=True, exist_ok=True)
    ensure_session_bundle(sdir, sandbox_mode=sandbox_override)
    label = f"{session}/{step}"
    script_path = _find_step_script(sdir, step)
    out_path = sdir / f"{step}.txt"

    aborted_marker = script_path.with_suffix(".aborted")
    overwrite = aborted_marker.exists()
    if overwrite:
        out_path.unlink(missing_ok=True)
        aborted_marker.unlink(missing_ok=True)
    elif script_path.exists() or out_path.exists():
        if sys.stdout.isatty() and not no_clipboard() and not headless:
            existing_lines = []
            if script_path.exists():
                existing_lines.append(f"Script: {script_path}")
            if out_path.exists():
                existing_lines.append(f"Output: {out_path}")
            step_hdr = format_session_header_lines(
                label=label, sdir=sdir, sandbox_mode=sandbox_override
            )
            if prompt_yes_no_box(
                "STEP ALREADY EXISTS",
                [*step_hdr, "", *existing_lines],
                f"Overwrite and re-run {label}?",
                default_yes=False,
                yes_status=f"✓ Overwriting {label}.",
                no_status=f"✗ Keeping existing {label}.",
                script_path=script_path if script_path.exists() else None,
                out_path=out_path if out_path.exists() else None,
            ):
                overwrite = True
                out_path.unlink(missing_ok=True)
            else:
                return 2
        if not overwrite:
            return not_run_exit(label, sdir, step, out_path, f"[{label}] NOT RUN: step already exists — output: {out_path}", headless=headless)
    if step_num > 1 and not _find_step_script(sdir, str(step_num - 1)).exists():
        prev_label = f"{session}/{step_num - 1}"
        allow_skip = False
        if sys.stdout.isatty() and not no_clipboard() and not headless:
            step_hdr = format_session_header_lines(
                label=label, sdir=sdir, sandbox_mode=sandbox_override
            )
            allow_skip = prompt_yes_no_box(
                "MISSING PREVIOUS STEP",
                [*step_hdr, "", f"Missing: {prev_label}"],
                f"Run {label} anyway?",
                default_yes=False,
                yes_status=f"✓ Proceeding with {label} (skipped {prev_label}).",
                no_status=f"✗ Canceled {label} (run {prev_label} first).",
            )
            if not allow_skip:
                return 2
        if not allow_skip:
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

    write_private(script_path, payload, overwrite=overwrite)
    return run_script(
        label,
        script_path,
        out_path,
        cleanup_on_abort=[script_path],
        auto_yes=auto_yes,
        sandbox_override=sandbox_override,
    )


def cmd_fix(
    ref: str, fix_code: str, auto_yes: bool = False, sandbox_override: str | None = None
) -> int:
    fix_code = _strip_trailing_fence(fix_code)
    headless = auto_yes or os.environ.get("RUN_BLOCK_HEADLESS") == "1"
    session, target = parse_ref(ref, allow_fix_step=True)
    sdir = ensure_base() / session
    src_script = _find_step_script(sdir, target)
    ext = src_script.suffix or _script_ext()
    new_step = next_fix_step(target)
    label = f"{session}/{new_step}"
    fix_path = sdir / f"{new_step}.fix"
    script_path = sdir / f"{new_step}{ext}"
    out_path = sdir / f"{new_step}.txt"

    if not src_script.exists():
        return not_run_exit(
            f"{session}/{target}",
            sdir,
            new_step,
            out_path,
            f"[{session}/{target}] NOT RUN: target script {src_script} does not exist",
        )

    if script_path.exists() or fix_path.exists():
        return not_run_exit(label, sdir, new_step, out_path, f"[{label}] NOT RUN: fix step already exists — output: {out_path}")
    out_path.unlink(missing_ok=True)
    if not fix_code.strip():
        return not_run_exit(label, sdir, new_step, out_path, f"[{label}] NOT RUN: empty fix on stdin")

    ast_ok, ast_err = validate_fix_ast(fix_code)
    if not ast_ok:
        return not_run_exit(
            label,
            sdir,
            new_step,
            out_path,
            f"[{label}] NOT RUN: unsafe construct in --fix ({ast_err})",
            headless=headless,
        )
    orig_text = src_script.read_text(encoding="utf-8")
    ns: dict[str, object] = {"__builtins__": dict(SAFE_FIX_BUILTINS), "text": orig_text, "re": re}
    try:
        exec(compile(fix_code, str(fix_path), "exec"), ns)
    except Exception as exc:
        return not_run_exit(
            label,
            sdir,
            new_step,
            out_path,
            f"[{label}] NOT RUN: fix raised {type(exc).__name__}: {exc}",
            headless=headless,
        )

    new_text = ns.get("text")
    if not isinstance(new_text, str):
        return not_run_exit(label, sdir, new_step, out_path, f"[{label}] NOT RUN: fix did not leave a string in 'text'")
    if new_text == orig_text:
        return not_run_exit(label, sdir, new_step, out_path, f"[{label}] NOT RUN: fix made no changes to {src_script}")

    write_private(fix_path, fix_code)
    write_private(script_path, new_text)
    diff = "".join(
        difflib.unified_diff(
            orig_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=f"{target}{ext}",
            tofile=f"{new_step}{ext}",
        )
    )
    header = [f"[{label}] patched {target}{ext} -> {new_step}{ext}:\n", diff]
    return run_script(
        label,
        script_path,
        out_path,
        header_lines=header,
        cleanup_on_abort=[fix_path, script_path],
        auto_yes=auto_yes,
        sandbox_override=sandbox_override,
    )


def _step_sort_key(stem: str) -> tuple[int, int]:
    if "_" in stem:
        b, s = stem.split("_", 1)
        return (int(b) if b.isdigit() else 0, int(s) if s.isdigit() else 0)
    return (int(stem) if stem.isdigit() else 0, 0)


def _step_status(sdir: Path, stem: str) -> str:
    if (sdir / f"{stem}.aborted").exists():
        return "ABORTED"
    out_p = sdir / f"{stem}.txt"
    if out_p.is_file():
        txt = out_p.read_text(encoding="utf-8", errors="replace")
        label = f"{sdir.name}/{stem}"
        matches = re.findall(rf"^\[{re.escape(label)}\]\s+(END|SUCCESS|FAILED|NOT RUN)([^\n]*)", txt, flags=re.MULTILINE)
        if matches:
            kind, rest = matches[-1]
            return (kind + rest.split("—")[0]).strip()
        return "DONE"
    return "SAVED"


def _find_latest_step(session: str | None = None) -> tuple[str, str]:
    base = ensure_base()
    if session:
        sdirs = [base / session] if (base / session).is_dir() else []
    else:
        sdirs = sorted(
            [p for p in base.iterdir() if p.is_dir()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    for sdir in sdirs:
        scripts = [p.stem for p in _iter_session_scripts(sdir)]
        if scripts:
            return sdir.name, scripts[-1]
    raise SystemExit(f"{prog_name()}: no saved blocks found in {base}")


def cmd_list(session: str | None = None) -> int:
    base = ensure_base()
    if not session:
        sdirs = sorted([p for p in base.iterdir() if p.is_dir()], key=lambda p: p.stat().st_mtime)
        if not sdirs:
            sys.stdout.write(f"No sessions in {base}\n")
            return 0
        sys.stdout.write(f"Sessions in {base}:\n")
        for sdir in sdirs:
            scripts = [p.stem for p in _iter_session_scripts(sdir)]
            has_bundle = (sdir / "0.txt").is_file()
            if scripts:
                last = f"{sdir.name}/{scripts[-1]} ({_step_status(sdir, scripts[-1])})"
            elif has_bundle:
                last = f"{sdir.name}/0 (BUNDLE)"
            else:
                last = "empty"
            sys.stdout.write(f"  {sdir.name:<8}  {len(scripts):>3} block(s)   last: {last}\n")
        session = sdirs[-1].name
        sys.stdout.write(f"\nRecent blocks in {session}:\n")
    else:
        sdir = base / session
        if not sdir.is_dir():
            raise SystemExit(f"{prog_name()}: session {session!r} not found in {base}")
        sys.stdout.write(f"Blocks in {session}:\n")
    sdir = base / session
    if (sdir / "0.txt").is_file():
        ref0 = f"{session}/0"
        sys.stdout.write(f"  {ref0:<10}  {'BUNDLE':<24}  Session context bundle (0.txt)\n")
    script_paths = _iter_session_scripts(sdir)
    for sp in script_paths[-15:]:
        stem = sp.stem
        st = _step_status(sdir, stem)
        sh_text = sp.read_text(encoding="utf-8", errors="replace")
        summary = summarize_script_actions(sh_text, work_dir=get_work_dir(sdir))
        rows = summary.get("rows") or []
        desc = "; ".join(f"{k}: {v}" for k, v in rows[:2]) if rows else ""
        if len(desc) > 56:
            desc = desc[:53] + "..."
        ref = f"{session}/{stem}"
        sys.stdout.write(f"  {ref:<10}  {st:<24}  {desc}\n")
    return 0


def cmd_show(ref: str | None = None) -> int:
    if ref:
        session, step = parse_ref(ref, allow_fix_step=True)
    else:
        session, step = _find_latest_step()
    sdir = ensure_base() / session
    script_path = _find_step_script(sdir, step)
    out_path = sdir / f"{step}.txt"
    if step == "0" and out_path.is_file():
        sys.stdout.write(f"=== [{session}/0] Bundle: {out_path} ===\n")
        sys.stdout.write(out_path.read_text(encoding="utf-8", errors="replace"))
        return 0
    if not script_path.is_file():
        raise SystemExit(f"{prog_name()}: block {session}/{step} not found ({script_path})")
    sys.stdout.write(f"=== [{session}/{step}] Script: {script_path} ({_step_status(sdir, step)}) ===\n")
    sys.stdout.write(script_path.read_text(encoding="utf-8", errors="replace"))
    if out_path.is_file():
        sys.stdout.write(f"\n=== [{session}/{step}] Output: {out_path} ===\n")
        sys.stdout.write(out_path.read_text(encoding="utf-8", errors="replace"))
    return 0


def cmd_retry(
    ref: str | None = None, auto_yes: bool = False, sandbox_override: str | None = None
) -> int:
    if ref:
        session, step = parse_ref(ref, allow_fix_step=True)
    else:
        session, step = _find_latest_step()
    sdir = ensure_base() / session
    script_path = _find_step_script(sdir, step)
    out_path = sdir / f"{step}.txt"
    if not script_path.is_file():
        raise SystemExit(f"{prog_name()}: block {session}/{step} not found ({script_path})")
    out_path.unlink(missing_ok=True)
    (sdir / f"{step}.aborted").unlink(missing_ok=True)
    return run_script(
        f"{session}/{step}",
        script_path,
        out_path,
        cleanup_on_abort=[],
        auto_yes=auto_yes,
        sandbox_override=sandbox_override,
    )


def _find_latest_session_dir() -> Path | None:
    base = ensure_base()
    sdirs = sorted(
        [p for p in base.iterdir() if p.is_dir()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return sdirs[0] if sdirs else None


def cmd_sandbox(argv: list[str]) -> int:
    prog = prog_name()
    if in_run_block():
        sys.stderr.write(f"{prog}: cannot modify session sandbox settings from inside a running block\n")
        return 2
    mode_arg: str | None = None
    session_arg: str | None = None
    for a in argv:
        if re.fullmatch(r"s\d+", a) and session_arg is None and mode_arg is not None:
            session_arg = a
        elif mode_arg is None and a.lower() in ("off", "0", "false", "on", "1", "true", "auto", "strict", "nonet", "no-net"):
            mode_arg = normalize_sandbox_mode(a)
        elif session_arg is None and re.fullmatch(r"[A-Za-z0-9._-]+", a) and (ensure_base() / a).is_dir():
            session_arg = a
        elif mode_arg is None:
            mode_arg = normalize_sandbox_mode(a)
        else:
            raise SystemExit(f"{prog}: usage: {prog} --sandbox [off|strict|nonet] [session]")

    base = ensure_base()
    sdir = (base / session_arg) if session_arg else _find_latest_session_dir()
    backend = detect_sandbox_backend()
    if mode_arg is None:
        cur_mode = get_sandbox_mode(sdir)
        sess_lbl = sdir.name if sdir is not None else "(no active session)"
        sys.stdout.write(
            f"Session: {sess_lbl}\n"
            f"Sandbox: {format_sandbox_header(cur_mode)}\n"
            f"Backend: {backend}\n"
        )
        return 0
    if sdir is None:
        sdir = start_session(session_arg, sandbox_mode=mode_arg)
    else:
        sdir.mkdir(mode=0o700, parents=True, exist_ok=True)
        set_session_bundle_header(sdir, "Sandbox", format_sandbox_header(mode_arg))
    sys.stdout.write(
        f"Updated {sdir.name}/0.txt -> Sandbox: {format_sandbox_header(mode_arg)} (backend: {backend})\n"
    )
    return 0


def _dir_size_bytes(path: Path) -> int:
    total = 0
    try:
        for p in path.rglob("*"):
            if p.is_file():
                try:
                    total += p.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def cmd_clean(argv: list[str]) -> int:
    prog = prog_name()
    keep = 5
    clean_all = False
    yes = False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--all":
            clean_all = True
            keep = 0
            i += 1
        elif a in ("-y", "--yes", "--force"):
            yes = True
            i += 1
        elif a == "--keep":
            if i + 1 >= len(argv):
                raise SystemExit(f"{prog}: --keep requires a non-negative integer")
            try:
                keep = int(argv[i + 1])
            except ValueError:
                raise SystemExit(f"{prog}: invalid --keep value: {argv[i + 1]!r}")
            if keep < 0:
                raise SystemExit(f"{prog}: --keep must be >= 0")
            i += 2
        elif a.startswith("--keep="):
            val_s = a.split("=", 1)[1]
            try:
                keep = int(val_s)
            except ValueError:
                raise SystemExit(f"{prog}: invalid --keep value: {val_s!r}")
            if keep < 0:
                raise SystemExit(f"{prog}: --keep must be >= 0")
            i += 1
        else:
            raise SystemExit(f"{prog}: usage: {prog} --clean [--keep N | --all] [--yes]")

    base = ensure_base()
    sdirs = sorted(
        [p for p in base.iterdir() if p.is_dir()],
        key=lambda p: (p.stat().st_mtime, p.name),
    )
    if clean_all or keep == 0:
        to_remove = sdirs
    elif len(sdirs) > keep:
        to_remove = sdirs[: len(sdirs) - keep]
    else:
        to_remove = []

    if not to_remove:
        sys.stdout.write(f"Nothing to clean in {base} ({len(sdirs)} session(s) kept).\n")
        return 0

    freed_bytes = sum(_dir_size_bytes(d) for d in to_remove)
    names = ", ".join(d.name for d in to_remove)
    if not yes and sys.stdin.isatty() and sys.stdout.isatty() and not no_clipboard():
        ok = prompt_yes_no_box(
            "CLEAN SESSIONS",
            [
                f"Directory: {base}",
                f"Remove: {len(to_remove)} session(s) ({names})",
                f"Free: {freed_bytes:,} bytes",
            ],
            f"Delete {len(to_remove)} session(s)?",
            default_yes=False,
            yes_status=f"✓ Removing {len(to_remove)} session(s).",
            no_status="✗ Clean canceled.",
        )
        if not ok:
            return 2

    for d in to_remove:
        shutil.rmtree(d, ignore_errors=True)
    kept = len(sdirs) - len(to_remove)
    sys.stdout.write(
        f"Cleaned {len(to_remove)} session(s) ({names}; {freed_bytes:,} bytes freed) from {base}; {kept} kept.\n"
    )
    return 0

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


def resolve_initial_session(base: Path) -> str:
    """Returns an existing prepared session (that has no step 1 yet) or the next new session name."""
    candidates: list[tuple[int, Path]] = []
    for p in base.iterdir():
        if p.is_dir():
            m = re.fullmatch(r"s(\d+)", p.name)
            if m:
                candidates.append((int(m.group(1)), p))
    if candidates:
        candidates.sort(key=lambda item: item[0])
        _, latest_dir = candidates[-1]
        has_blocks = bool(_iter_session_scripts(latest_dir)) or (latest_dir / "1.txt").exists() or (latest_dir / "1.aborted").exists()
        if not has_blocks:
            return latest_dir.name
    return next_session_name(base)


def start_session(name: str | None = None, force: bool = False) -> Path:
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
                ok = prompt_yes_no_box(
                    f"[{name}] [!] SESSION ALREADY EXISTS",
                    [f"Session directory already exists: {sdir}"],
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
    if headless or os.environ.get("RUN_BLOCK_HEADLESS") == "1":
        sys.stdout.write(line)
    else:
        sys.stdout.write(format_info_box(f"[{label}] [!] NOT RUN", [detail]) + "\n")
    sys.stdout.flush()
    err_target = sdir / f"{step_name}.error.txt" if out_path.exists() else out_path
    try:
        write_private(err_target, line, overwrite=True)
        if not headless and os.environ.get("RUN_BLOCK_HEADLESS") != "1":
            offer_clipboard_copy(label, err_target, ok=False, rc=rc)
    except Exception:
        pass
    return rc


def run_script(
    label: str,
    script_path: Path,
    out_path: Path,
    header_lines: list[str] | None = None,
    cleanup_on_abort: list[Path] | None = None,
    auto_yes: bool = False,
) -> int:
    headless = auto_yes or os.environ.get("RUN_BLOCK_HEADLESS") == "1"
    work_dir = get_work_dir(script_path.parent)
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
        start_line = f"[{label}] START (script: {script_path})\n\n"
        msg = chk.stdout or "syntax check failed\n"
        end_line = f"[{label}] END (syntax error, exit {chk.returncode}) — output: {out_path}\n"
        full_output = start_line + msg + end_line
        if headless:
            sys.stdout.write(full_output)
        else:
            box_lines = [f"Script: {script_path}", *(msg.rstrip("\n").splitlines())]
            sys.stdout.write(format_info_box(f"[{label}] [!] SYNTAX ERROR (exit {chk.returncode})", box_lines) + "\n")
        sys.stdout.flush()
        write_private(out_path, full_output)
        if not headless:
            offer_clipboard_copy(label, out_path, ok=False, rc=chk.returncode)
        return chk.returncode

    aborted_marker = script_path.with_suffix(".aborted")
    summary_obj = summarize_script_actions(script_text, work_dir=work_dir)
    approved, abort_reason = confirm_execution(
        label, script_text, summary=summary_obj, script_path=script_path, auto_yes=headless
    )
    if not approved:
        write_private(aborted_marker, "aborted\n", overwrite=True)
        reason_str = abort_reason or f"aborted by user (re-run with: {prog_name()} --retry {label})"
        return not_run_exit(
            label, script_path.parent, script_path.stem, out_path, f"[{label}] NOT RUN: {reason_str}", rc=130, headless=headless
        )
    aborted_marker.unlink(missing_ok=True)

    start_line = f"[{label}] START (script: {script_path})\n"
    log_chunks: list[str] = [start_line]
    start_box_lines = [f"Script: {script_path}"]
    for h in header_lines or []:
        log_chunks.append(h)
        for hl in h.rstrip("\n").splitlines():
            start_box_lines.append(hl)
    log_chunks.append("\n")
    if headless:
        sys.stdout.write("".join(log_chunks))
    else:
        sys.stdout.write(format_info_box(f"[{label}] START", start_box_lines) + "\n\n")
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

    child_env = {**os.environ, "IN_RUN_BLOCK": "1"}
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
    if log_chunks and not log_chunks[-1].endswith("\n"):
        log_chunks.append("\n")
        sys.stdout.write("\n")
    exit_str = f" (exit {rc})" if rc != 0 else ""
    end_line = f"\n[{label}] END{exit_str} — output: {out_path}\n"
    log_chunks.append(end_line)
    if headless:
        sys.stdout.write(end_line)
    elif in_run_block() or not sys.stdout.isatty() or clipboard_mode() != "prompt":
        sys.stdout.write("\n" + format_info_box(f"[{label}] END{exit_str}", [f"Output: {out_path}"]) + "\n")
    sys.stdout.flush()
    full_output = CR_LINE_RE.sub("", ANSI_RE.sub("", "".join(log_chunks))).replace("\r\n", "\n")
    write_private(out_path, full_output)
    if not headless:
        clip_target = resolve_clipboard_target(out_path, full_output)
        offer_clipboard_copy(label, clip_target, ok=(rc == 0), rc=rc)
    return rc


def cmd_normal(ref: str, payload: str, auto_yes: bool = False) -> int:
    headless = auto_yes or os.environ.get("RUN_BLOCK_HEADLESS") == "1"
    session, step = parse_ref(ref, allow_fix_step=False)
    step_num = int(step)
    if step_num < 1:
        raise SystemExit(f"{prog_name()}: step number must be >= 1")
    sdir = ensure_base() / session
    sdir.mkdir(mode=0o700, parents=True, exist_ok=True)
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
            if prompt_yes_no_box(
                f"[{label}] [!] STEP ALREADY EXISTS",
                [f"Step file already exists: {script_path}"],
                f"Overwrite and re-run {label}?",
                default_yes=False,
                yes_status=f"✓ Overwriting {label}.",
                no_status=f"✗ Keeping existing {label}.",
            ):
                overwrite = True
                out_path.unlink(missing_ok=True)
        if not overwrite:
            return not_run_exit(label, sdir, step, out_path, f"[{label}] NOT RUN: step already exists — output: {out_path}", headless=headless)
    if step_num > 1 and not _find_step_script(sdir, str(step_num - 1)).exists():
        prev_label = f"{session}/{step_num - 1}"
        allow_skip = False
        if sys.stdout.isatty() and not no_clipboard() and not headless:
            allow_skip = prompt_yes_no_box(
                f"[{label}] [!] MISSING PREVIOUS STEP",
                [f"Previous step {prev_label} has not been run yet."],
                f"Run {label} anyway?",
                default_yes=False,
                yes_status=f"✓ Proceeding with {label} (skipped {prev_label}).",
                no_status=f"✗ Canceled {label} (run {prev_label} first).",
            )
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
    return run_script(label, script_path, out_path, cleanup_on_abort=[script_path], auto_yes=auto_yes)


def cmd_fix(ref: str, fix_code: str, auto_yes: bool = False) -> int:
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

    orig_text = src_script.read_text(encoding="utf-8")
    ns: dict[str, object] = {"text": orig_text, "re": re}
    try:
        exec(compile(fix_code, str(fix_path), "exec"), ns)
    except Exception as exc:
        return not_run_exit(label, sdir, new_step, out_path, f"[{label}] NOT RUN: fix raised {type(exc).__name__}: {exc}")

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
    return run_script(label, script_path, out_path, header_lines=header, cleanup_on_abort=[fix_path, script_path], auto_yes=auto_yes)


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
        summary = summarize_script_actions(sh_text)
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


def cmd_retry(ref: str | None = None, auto_yes: bool = False) -> int:
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
    return run_script(f"{session}/{step}", script_path, out_path, cleanup_on_abort=[], auto_yes=auto_yes)


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
            "[CLEAN] [!] PRUNE SESSIONS",
            [
                f"Directory: {base}",
                f"Sessions to remove ({len(to_remove)}): {names}",
                f"Disk space to free: {freed_bytes:,} bytes",
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

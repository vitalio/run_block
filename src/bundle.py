def format_sandbox_header(mode: str) -> str:
    norm = normalize_sandbox_mode(mode)
    if norm == "strict":
        return "strict (rw: Workdir, /tmp; secrets: hidden; net: on)"
    if norm == "nonet":
        return "nonet (rw: Workdir, /tmp; secrets: hidden; net: off)"
    if norm == "off":
        return "off"
    return norm


def format_start_bundle(
    session_name: str,
    stdin_body: str = "",
    work_dir: Path | None = None,
    now: datetime | None = None,
    sandbox_mode: str | None = None,
) -> dict[str, object]:
    wdir = (work_dir if work_dir is not None else get_work_dir()).resolve()
    sb_mode = get_sandbox_mode(override=sandbox_mode)
    sb_hdr = format_sandbox_header(sb_mode)
    ts = (now or datetime.now().astimezone()).strftime("%Y-%m-%d %H:%M %Z").strip()
    clean_body = stdin_body.strip()
    bundle_header_lines = [
        f"Session: {session_name}",
        f"Next-Block: {session_name}/1",
        f"Workdir: {wdir}",
        f"Sandbox: {sb_hdr}",
        f"Date: {ts}",
    ]
    bundle_header_text = "\n".join(bundle_header_lines) + "\n"
    full_text = bundle_header_text + ("\n" + clean_body + "\n" if clean_body else "")
    total_lines = len(full_text.splitlines())
    total_tokens = count_tokens(full_text.encode("utf-8"))["gpt"]
    console_lines = [
        f"Session: {session_name}",
        f"Next-Block: {session_name}/1",
        f"Date: {ts}",
        f"Workdir: {wdir}",
        f"Sandbox: {sb_hdr}",
        f"Total: {total_lines} lines (~{total_tokens} tokens)",
    ]
    return {
        "console_lines": console_lines,
        "full": full_text,
        "total_lines": total_lines,
        "total_tokens": total_tokens,
        "sandbox": sb_mode,
    }


def set_session_bundle_header(sdir: Path, key: str, value: str) -> None:
    bundle_path = ensure_session_bundle(sdir)
    text = bundle_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    header_end = 0
    target_idx = -1
    key_lower = key.lower()
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("====="):
            header_end = idx
            break
        m = BUNDLE_HEADER_RE.match(stripped)
        if not m:
            header_end = idx
            break
        k = re.sub(r"\s+", "-", m.group(1).strip().lower())
        if k == key_lower:
            target_idx = idx
        header_end = idx + 1
    new_line = f"{key}: {value}"
    if target_idx >= 0:
        lines[target_idx] = new_line
    else:
        insert_at = max(0, header_end - 1) if header_end > 0 else 0
        lines.insert(insert_at, new_line)
    write_private(bundle_path, "\n".join(lines) + "\n", overwrite=True)


def cmd_start(argv: list[str], stdin_text: str | None = None, sandbox_override: str | None = None) -> int:
    prog = prog_name()
    force = False
    session_arg: str | None = None
    sb_arg: str | None = sandbox_override
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--force":
            force = True
            i += 1
        elif a == "--no-sandbox":
            sb_arg = "off"
            i += 1
        elif a == "--sandbox":
            if i + 1 < len(argv) and not argv[i + 1].startswith("-"):
                sb_arg = argv[i + 1]
                i += 2
            else:
                sb_arg = "strict"
                i += 1
        elif a.startswith("--sandbox="):
            sb_arg = a.split("=", 1)[1] or "strict"
            i += 1
        elif a == "--session":
            if i + 1 >= len(argv):
                raise SystemExit(f"{prog}: --session requires an argument")
            session_arg = argv[i + 1]
            i += 2
        elif a.startswith("-"):
            raise SystemExit(
                f"{prog}: usage: <command> | {prog} [--start] [--session NAME] [--sandbox [MODE]] [--force]"
            )
        else:
            if session_arg is None and re.fullmatch(r"s\d+", a):
                session_arg = a
                i += 1
            else:
                raise SystemExit(
                    f"{prog}: usage: <command> | {prog} [--start] [--session NAME] [--sandbox [MODE]] [--force]"
                )

    if stdin_text is None:
        if sys.stdin.isatty():
            sys.stderr.write(
                f"{prog}: --start expects a context bundle on stdin (e.g. '{prog} --start < context.txt')\n"
            )
            return 2
        stdin_text = sys.stdin.read()

    sdir = start_session(session_arg, force=force, sandbox_mode=sb_arg)
    session_name = sdir.name
    bundle_path = sdir / "0.txt"
    res = format_start_bundle(session_name=session_name, stdin_body=stdin_text, sandbox_mode=sb_arg)
    write_private(bundle_path, str(res["full"]), overwrite=True)
    wdir = get_work_dir(sdir).resolve()
    sb_mode = get_sandbox_mode(sdir, override=sb_arg)
    body_lines = [
        f"Next-Block: {session_name}/1",
        f"Workdir: {wdir}",
    ]
    if sb_mode != "off":
        body_lines.append(f"Sandbox: {format_sandbox_header(sb_mode)}")
    body_lines.append(f"Bundle: {bundle_path}")
    label0 = f"{session_name}/0"
    if not in_run_block() and sys.stdout.isatty() and clipboard_mode() == "prompt" and clipboard_command(bundle_path) is not None:
        offer_clipboard_copy(label0, bundle_path, ok=True, rc=0, title_kind="START BUNDLE", extra_lines=body_lines)
    else:
        full_body = build_box_body_lines(bundle_path, rc=0, stats=stats_line(bundle_path), extra_lines=body_lines)
        sys.stdout.write(format_info_box(f"{label0} · START BUNDLE", full_body) + "\n")
        sys.stdout.flush()
        if not in_run_block():
            offer_clipboard_copy(label0, bundle_path, ok=True, rc=0, title_kind="START BUNDLE", extra_lines=body_lines)
    return 0


def ensure_session_bundle(
    sdir: Path, work_dir: Path | None = None, sandbox_mode: str | None = None
) -> Path:
    bundle_path = sdir / "0.txt"
    if not bundle_path.is_file():
        res = format_start_bundle(
            session_name=sdir.name, stdin_body="", work_dir=work_dir, sandbox_mode=sandbox_mode
        )
        write_private(bundle_path, str(res["full"]), overwrite=True)
    return bundle_path

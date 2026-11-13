def format_start_bundle(
    session_name: str,
    stdin_body: str,
    work_dir: Path | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    wdir = (work_dir if work_dir is not None else get_work_dir()).resolve()
    ts = (now or datetime.now().astimezone()).strftime("%Y-%m-%d %H:%M %Z").strip()
    clean_body = stdin_body.strip()
    bundle_header_lines = [
        f"Session: {session_name}",
        f"Next block: {session_name}/1",
        f"Workdir: {wdir}",
    ]
    bundle_header_text = "\n".join(bundle_header_lines) + "\n"
    full_text = bundle_header_text + ("\n" + clean_body + "\n" if clean_body else "")
    total_lines = len(full_text.splitlines())
    total_tokens = count_tokens(full_text.encode("utf-8"))["gpt"]
    console_lines = [
        f"Session: {session_name}",
        f"Next block: {session_name}/1",
        f"Date: {ts}",
        f"Workdir: {wdir}",
        f"Total: {total_lines} lines (~{total_tokens} tokens)",
    ]
    return {
        "console_lines": console_lines,
        "full": full_text,
        "total_lines": total_lines,
        "total_tokens": total_tokens,
    }


def cmd_start(argv: list[str], stdin_text: str | None = None) -> int:
    prog = prog_name()
    force = False
    session_arg: str | None = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--force":
            force = True
            i += 1
        elif a == "--session":
            if i + 1 >= len(argv):
                raise SystemExit(f"{prog}: --session requires an argument")
            session_arg = argv[i + 1]
            i += 2
        elif a.startswith("-"):
            raise SystemExit(f"{prog}: usage: agents_bundle | {prog} [--start] [--session NAME] [--force]")
        else:
            if session_arg is None and re.fullmatch(r"s\d+", a):
                session_arg = a
                i += 1
            else:
                raise SystemExit(f"{prog}: usage: agents_bundle | {prog} [--start] [--session NAME] [--force]")

    if stdin_text is None:
        if sys.stdin.isatty():
            sys.stderr.write(
                f"{prog}: --start expects a context bundle on stdin (e.g. 'agents_bundle | {prog}')\n"
            )
            return 2
        stdin_text = sys.stdin.read()

    sdir = start_session(session_arg, force=force)
    session_name = sdir.name
    bundle_path = sdir / "0.txt"
    res = format_start_bundle(session_name=session_name, stdin_body=stdin_text)
    write_private(bundle_path, str(res["full"]), overwrite=True)
    wdir = get_work_dir().resolve()
    body_lines = [
        f"Next block: {session_name}/1",
        f"Workdir:    {wdir}",
        f"Bundle:     {bundle_path}",
    ]
    label0 = f"{session_name}/0"
    if not in_run_block() and sys.stdout.isatty() and clipboard_mode() == "prompt" and clipboard_command(bundle_path) is not None:
        offer_clipboard_copy(label0, bundle_path, ok=True, rc=0, title_kind="START BUNDLE", extra_lines=body_lines)
    else:
        st = stats_line(bundle_path)
        hdr = f"{label0} · START BUNDLE ({st})" if st else f"{label0} · START BUNDLE"
        sys.stdout.write(format_info_box(hdr, body_lines) + "\n")
        sys.stdout.flush()
        if not in_run_block():
            offer_clipboard_copy(label0, bundle_path, ok=True, rc=0, title_kind="START BUNDLE", extra_lines=body_lines)
    return 0

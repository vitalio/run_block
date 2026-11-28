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
    prompt: str | list[str] | tuple[str, ...] | None = None,
) -> dict[str, object]:
    stdin_headers, raw_body = parse_stdin_preamble(stdin_body)
    boundary = get_bundle_boundary(stdin_headers)
    protocol = get_bundle_protocol(stdin_headers)
    if protocol is not None and protocol not in SUPPORTED_BUNDLE_PROTOCOLS:
        sys.stderr.write(
            f"{prog_name()}: unsupported Bundle-Protocol: {protocol} "
            f"(supported: {', '.join(SUPPORTED_BUNDLE_PROTOCOLS)})\n"
        )
    raw_body = inject_embedded_block_rule(raw_body, boundary=boundary)
    raw_body = inject_embedded_prompt(raw_body, prompt=prompt, boundary=boundary)
    clean_body, bundle_plan = parse_bundle_fragments(raw_body, boundary=boundary)
    exposed_headers = filter_exposed_headers(stdin_headers)
    if work_dir is not None:
        wdir = work_dir.resolve()
    else:
        cwd_setting, _ = get_setting("work_dir")
        hdr_wdir: Path | None = None
        if cwd_setting.lower() == "auto":
            hdr_map = {k.lower(): v for k, v in stdin_headers}
            hdr_wdir = _resolve_existing_dir(hdr_map.get("workdir") or hdr_map.get("work-dir") or "")
        wdir = (hdr_wdir if hdr_wdir is not None else get_work_dir()).resolve()
    sb_mode = get_sandbox_mode(override=sandbox_mode)
    sb_hdr = format_sandbox_header(sb_mode)
    dt_utc = now.astimezone(timezone.utc) if now is not None else datetime.now(timezone.utc)
    ts = dt_utc.strftime("%Y-%m-%d %H:%M UTC")
    bundle_header_lines = [
        f"Session: {session_name}",
        f"Next-Block: {session_name}/1",
        f"Workdir: {wdir}",
    ]
    if normalize_sandbox_mode(sb_mode) != "off":
        bundle_header_lines.append(f"Sandbox: {sb_hdr}")
    bundle_header_lines.append(f"Date: {ts}")
    for exp_k, exp_v in exposed_headers:
        bundle_header_lines.append(f"{exp_k}: {exp_v}")
    bundle_header_text = "\n".join(bundle_header_lines) + "\n"
    full_text = bundle_header_text + ("\n" + clean_body + "\n" if clean_body else "")
    norm_raw_body = raw_body.strip("\n")
    raw_full_text = bundle_header_text + ("\n" + norm_raw_body + "\n" if norm_raw_body else "")
    full_tok = count_tokens(full_text.encode("utf-8"))
    total_lines = int(full_tok["lines"])
    total_chars = int(full_tok["chars"])
    total_tokens = int(full_tok["gpt"])
    fn_reconcile = globals().get("reconcile_bundle_plan")
    if callable(fn_reconcile):
        bundle_plan = fn_reconcile(bundle_plan, full_text)
    console_lines = [
        f"Session: {session_name}",
        f"Next-Block: {session_name}/1",
        f"Date: {ts}",
        f"Workdir: {wdir}",
        f"Sandbox: {sb_hdr}",
        f"Total: {total_lines} line{'s' if total_lines != 1 else ''} · {_human_chars(total_chars)} (~{total_tokens} tokens)",
    ]
    return {
        "console_lines": console_lines,
        "full": full_text,
        "raw_full": raw_full_text,
        "raw_body": raw_body,
        "stdin_headers": stdin_headers,
        "exposed_headers": exposed_headers,
        "bundle_plan": bundle_plan,
        "total_lines": total_lines,
        "total_chars": total_chars,
        "total_tokens": total_tokens,
        "sandbox": sb_mode,
    }


def _update_bundle_text_header(text: str, key: str, value: str) -> str:
    lines = text.splitlines()
    header_end = 0
    target_idx = -1
    key_lower = re.sub(r"\s+", "-", key.strip().lower())
    remove_line = key_lower == "sandbox" and normalize_sandbox_mode(value.split()[0] if value.strip() else "") == "off"
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
    if remove_line:
        if target_idx >= 0:
            lines.pop(target_idx)
    else:
        new_line = f"{key}: {value}"
        if target_idx >= 0:
            lines[target_idx] = new_line
        else:
            insert_at = max(0, header_end - 1) if header_end > 0 else 0
            lines.insert(insert_at, new_line)
    return "\n".join(lines) + "\n"


def set_session_bundle_header(sdir: Path, key: str, value: str) -> None:
    bundle_path = ensure_session_bundle(sdir)
    text = bundle_path.read_text(encoding="utf-8", errors="replace")
    write_private(bundle_path, _update_bundle_text_header(text, key, value), overwrite=True)
    raw_path = sdir / "0.raw"
    if raw_path.is_file():
        raw_text = raw_path.read_text(encoding="utf-8", errors="replace")
        write_private(raw_path, _update_bundle_text_header(raw_text, key, value), overwrite=True)


def cmd_start(
    argv: list[str],
    stdin_text: str | None = None,
    sandbox_override: str | None = None,
    prompt: str | list[str] | tuple[str, ...] | None = None,
    profile: str | None = None,
) -> int:
    prog = prog_name()
    start_usage = (
        f"{prog}: usage: <command> | {prog} [--start] [-p TEXT] [-P NAME] [--session NAME] [--sandbox [MODE]] [--force]"
    )
    force = False
    session_arg: str | None = None
    sb_arg: str | None = sandbox_override
    prompts: list[str] = []
    if prompt is not None:
        if isinstance(prompt, str):
            prompts.append(prompt)
        else:
            prompts.extend(str(p) for p in prompt)
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--force":
            force = True
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
        elif a.startswith("--session="):
            val = a.split("=", 1)[1]
            if not val:
                raise SystemExit(f"{prog}: --session requires an argument")
            session_arg = val
            i += 1
        elif a in ("-p", "--prompt"):
            if i + 1 >= len(argv):
                raise SystemExit(f"{prog}: {a} requires an argument")
            prompts.append(argv[i + 1])
            i += 2
        elif a.startswith("--prompt="):
            prompts.append(a.split("=", 1)[1])
            i += 1
        elif a.startswith("-"):
            raise SystemExit(start_usage)
        else:
            if session_arg is None and re.fullmatch(r"s\d+", a):
                session_arg = a
                i += 1
            else:
                raise SystemExit(start_usage)

    if in_run_block():
        sys.stderr.write(f"{prog}: cannot start a new session from inside a running block\n")
        return 2

    if stdin_text is None:
        stdin_text = "" if sys.stdin.isatty() else sys.stdin.read()

    sdir = start_session(session_arg, force=force, sandbox_mode=sb_arg)
    session_name = sdir.name
    bundle_path = sdir / "0"
    res = format_start_bundle(
        session_name=session_name,
        stdin_body=stdin_text,
        sandbox_mode=sb_arg,
        prompt=prompts,
    )
    write_private(bundle_path, str(res["full"]), overwrite=True)
    raw_path = sdir / "0.raw"
    if isinstance(res.get("bundle_plan"), dict) and res["bundle_plan"].get("protocol") == "boundary":
        write_private(raw_path, str(res.get("raw_full") or res["full"]), overwrite=True)
    else:
        raw_path.unlink(missing_ok=True)
    stdin_headers = list(res.get("stdin_headers") or [])
    bundle_plan = res.get("bundle_plan")
    write_session_meta(
        sdir,
        stdin_headers,
        bundle_plan=bundle_plan if isinstance(bundle_plan, dict) else None,
    )
    persist_session_profile(sdir, profile)
    render_start_session_card(sdir)
    return 0


def persist_session_profile(sdir: Path, override: str | None = None) -> str | None:
    """Stores the resolved model profile name (CLI > env > role > default) in <session>/meta.json."""
    role = parse_bundle_headers(sdir).get("role")
    try:
        resolved = resolve_profile(role, override=override)
    except ValueError as exc:
        if override is not None:
            raise SystemExit(f"{prog_name()}: {exc}") from None
        sys.stderr.write(f"{prog_name()}: warning: {exc}\n")
        return None
    if resolved is None:
        return None
    name = str(resolved["name"])
    update_session_meta(sdir, profile=name)
    return name


def render_start_session_card(sdir: Path, *, offer_copy: bool = True) -> None:
    session_name = sdir.name
    bundle_path = sdir / "0"
    body_lines = [f"Bundle: {bundle_path}"]
    label0 = f"{session_name}/0"
    if (
        offer_copy
        and not in_run_block()
        and sys.stdout.isatty()
        and clipboard_mode() == "prompt"
        and clipboard_command(bundle_path) is not None
    ):
        offer_clipboard_copy(label0, bundle_path, rc=0, title_kind="START SESSION", extra_lines=body_lines, sdir=sdir)
    else:
        full_body = build_box_body_lines(
            bundle_path, rc=0, stats=stats_line(bundle_path), extra_lines=body_lines, label=label0, sdir=sdir, title_kind="START SESSION"
        )
        sys.stdout.write(format_info_box("START SESSION", full_body) + "\n")
        sys.stdout.flush()
        if offer_copy and not in_run_block():
            offer_clipboard_copy(label0, bundle_path, rc=0, title_kind="START SESSION", extra_lines=body_lines, sdir=sdir)


def refresh_bundle_meta(bundle_path: Path) -> None:
    if not bundle_path.is_file():
        return
    sdir = _resolve_session_dir(path_hint=bundle_path)
    if sdir is None:
        return
    fn_plan = globals().get("refresh_bundle_plan_meta")
    if callable(fn_plan):
        fn_plan(sdir, bundle_path)


def ensure_session_bundle(
    sdir: Path, work_dir: Path | None = None, sandbox_mode: str | None = None
) -> Path:
    bundle_path = sdir / "0"
    if not bundle_path.is_file():
        res = format_start_bundle(
            session_name=sdir.name, stdin_body="", work_dir=work_dir, sandbox_mode=sandbox_mode
        )
        write_private(bundle_path, str(res["full"]), overwrite=True)
    return bundle_path

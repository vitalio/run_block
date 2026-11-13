def default_start_template(prog: str | None = None) -> str:
    cmd = prog or prog_name()
    lines = [
        f"# {START_FILE_NAME} — session context bundle specification for '{cmd} --start'",
        "# Plain lines are file paths (read directly as UTF-8 relative to the project root).",
        "# Lines starting with '$ ' (or '! ') are shell commands executed in the project directory.",
        "",
        f"$ {cmd} --agents",
        "",
        "AGENTS.md",
        "",
        "$ git status -sb",
        "$ git branch -vv",
        "$ git log --oneline -10",
        "",
    ]
    return "\n".join(lines)


def cmd_init_start(force: bool = False, target_dir: Path | None = None) -> int:
    prog = prog_name()
    base_dir = target_dir if target_dir is not None else Path.cwd()
    path = base_dir / START_FILE_NAME
    if path.exists() and not force:
        sys.stderr.write(f"{prog}: {path} already exists (use --force to overwrite)\n")
        return 2
    path.write_text(default_start_template(prog), encoding="utf-8")
    sys.stdout.write(f"{prog}: wrote starter {START_FILE_NAME} to {path}\n")
    return 0


def find_start_file(work_dir: Path) -> tuple[Path | None, Path]:
    cwd = Path.cwd().resolve()
    wdir = work_dir.resolve()
    # Walk from cwd up to work_dir (if cwd is inside work_dir)
    if cwd == wdir or wdir in cwd.parents:
        cur = cwd
        while True:
            candidate = cur / START_FILE_NAME
            if candidate.is_file():
                return candidate, cur
            if cur == wdir or cur.parent == cur:
                break
            cur = cur.parent
    wdir_candidate = wdir / START_FILE_NAME
    if wdir_candidate.is_file():
        return wdir_candidate, wdir
    return None, wdir


def parse_start_spec(text: str) -> list[tuple[str, str]]:
    """Returns list of (kind, value) where kind is 'file' or 'cmd'."""
    entries: list[tuple[str, str]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("$ ") or line.startswith("! "):
            cmd_str = line[2:].strip()
            if cmd_str:
                entries.append(("cmd", cmd_str))
        elif line in ("$", "!"):
            continue
        else:
            entries.append(("file", line))
    return entries


def _run_start_command(cmd_str: str, cwd: Path) -> tuple[int, str]:
    prog = prog_name()
    self_path = str(Path(__file__).resolve())
    # If the command invokes '<prog> --agents' directly, call our own agents_markdown() in-process
    if re.match(rf"^(?:{re.escape(prog)}|run_block)\s+--(?:agents(?:-md|-rules)?|rules)(?:\s+.*)?$", cmd_str):
        try:
            tokens = shlex.split(cmd_str)
            flag = tokens[1]
            parts = tokens[2:]
            if any(a in ("--list", "-l") for a in parts):
                pass
            else:
                def_tgt = "workflow" if flag in ("--agents-rules", "--rules") else "default"
                return 0, rules_markdown(parts, work_dir=cwd, default_target=def_tgt, prog=prog).rstrip()
        except SystemExit as exc:
            return 1, str(exc)
    if re.match(rf"^(?:{re.escape(prog)}|run_block)\s+--tree(?:\s+.*)?$", cmd_str):
        try:
            parts = shlex.split(cmd_str)[2:]
            return 0, _tree_from_args(parts, default_dir=cwd).rstrip()
        except SystemExit as exc:
            return 1, str(exc)
    shell_bin, _ = get_setting("shell")
    shell_args = [shell_bin, "-NoProfile", "-Command", cmd_str] if _is_powershell(shell_bin) else [shell_bin, "-c", cmd_str]
    env = {**os.environ, "IN_RUN_BLOCK": "1", "PYTHONUTF8": "1"}
    # Ensure the directory containing this script is on PATH
    script_dir = str(Path(self_path).parent)
    env["PATH"] = f"{script_dir}{os.pathsep}{env.get('PATH', '')}"
    try:
        r = subprocess.run(
            shell_args,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            check=False,
        )
        return r.returncode, r.stdout.decode("utf-8", errors="replace").rstrip()
    except OSError as exc:
        return 1, f"[error running {cmd_str!r}: {exc}]"


def build_start_bundle(
    session_name: str,
    work_dir: Path | None = None,
    extra_files: list[str] | None = None,
    prompt_text: str | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    prog = prog_name()
    wdir = (work_dir if work_dir is not None else get_work_dir()).resolve()
    start_file, spec_dir = find_start_file(wdir)
    if start_file is not None:
        entries = parse_start_spec(start_file.read_text(encoding="utf-8"))
        spec_source = str(start_file)
    else:
        spec_source = "built-in defaults"
        entries = [
            ("cmd", f"{prog} --agents"),
        ]
        if (spec_dir / "AGENTS.md").is_file():
            entries.append(("file", "AGENTS.md"))
        if (spec_dir / ".git").exists():
            entries.append(("cmd", "git status -sb"))

    sections: list[tuple[str, str]] = []
    warnings: list[str] = []
    included_files: set[Path] = set()

    def add_file_section(rel_path: str, base_folder: Path, explicit: bool) -> None:
        clean = rel_path.strip()
        if not clean:
            return
        p = (base_folder / clean).resolve() if not Path(clean).is_absolute() else Path(clean).resolve()
        if p in included_files:
            return
        if not p.is_file():
            if explicit or start_file is not None:
                warnings.append(f"missing file: {clean}")
            return
        included_files.add(p)
        try:
            disp = str(p.relative_to(spec_dir))
        except ValueError:
            disp = str(p)
        content = p.read_text(encoding="utf-8", errors="replace").rstrip()
        sections.append((f"File: {disp}", content))

    for kind, val in entries:
        if kind == "file":
            add_file_section(val, spec_dir, explicit=False)
        elif kind == "cmd":
            rc, out = _run_start_command(val, spec_dir)
            if rc != 0:
                warnings.append(f"command exited {rc}: {val}")
            sections.append((f"$ {val}", out))

    for extra in extra_files or []:
        add_file_section(extra, Path.cwd().resolve(), explicit=True)

    if prompt_text and prompt_text.strip():
        sections.append(("Prompt", prompt_text.strip()))

    ts = (now or datetime.now().astimezone()).strftime("%Y-%m-%d %H:%M %Z").strip()
    manifest_lines: list[str] = []
    body_blocks: list[str] = []
    for title, content in sections:
        n_lines = len(content.splitlines()) if content else 0
        t_counts = count_tokens(content.encode("utf-8"))
        approx_tok = t_counts["gpt"]
        manifest_lines.append(f"  - {title}: {n_lines} lines (~{approx_tok} tokens)")
        body_blocks.append(f"===== {title} =====\n{content}\n")

    console_header_lines = [
        f"# {prog} session context bundle",
        f"Session: {session_name}",
        f"Next block: {session_name}/1",
        f"Date: {ts}",
        f"Workdir: {spec_dir}",
        f"Spec: {spec_source}",
        "Included sections:",
        *manifest_lines,
    ]
    if warnings:
        console_header_lines.append("Warnings:")
        console_header_lines.extend(f"  - {w}" for w in warnings)

    bundle_header_lines = [
        f"Session: {session_name}",
        f"Next block: {session_name}/1",
        f"Workdir: {spec_dir}",
    ]

    header_text = "\n".join(console_header_lines) + "\n"
    bundle_header_text = "\n".join(bundle_header_lines) + "\n"
    body_text = "\n".join(body_blocks)
    full_text = bundle_header_text + "\n" + body_text
    total_lines = len(full_text.splitlines())
    total_tokens = count_tokens(full_text.encode("utf-8"))["gpt"]
    return {
        "header": header_text,
        "body": body_text,
        "full": full_text,
        "warnings": warnings,
        "total_lines": total_lines,
        "total_tokens": total_tokens,
    }


def cmd_start(argv: list[str]) -> int:
    prog = prog_name()
    force = False
    session_arg: str | None = None
    prompt_parts: list[str] = []
    extra_files: list[str] = []
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
        elif a in ("-p", "--prompt"):
            if i + 1 >= len(argv):
                raise SystemExit(f"{prog}: {a} requires an argument")
            prompt_parts.append(argv[i + 1])
            i += 2
        elif a.startswith("-"):
            raise SystemExit(f"{prog}: unknown option for --start: {a}")
        else:
            extra_files.append(a)
            i += 1

    # Backward compatibility: if a single positional argument is not an existing file and matches session name (e.g. s2)
    if session_arg is None and len(extra_files) == 1 and not Path(extra_files[0]).exists() and re.fullmatch(r"s\d+", extra_files[0]):
        session_arg = extra_files.pop(0)

    sdir = start_session(session_arg, force=force)
    session_name = sdir.name
    bundle_path = sdir / "0.txt"
    prompt_text = "\n\n".join(prompt_parts) if prompt_parts else None
    res = build_start_bundle(
        session_name=session_name,
        extra_files=extra_files,
        prompt_text=prompt_text,
    )
    write_private(bundle_path, str(res["full"]), overwrite=True)
    hdr_lines = str(res["header"]).rstrip("\n").splitlines()
    if hdr_lines and hdr_lines[0].startswith("# "):
        hdr_lines = hdr_lines[1:]
    hdr_lines.append(f"Total: {res['total_lines']} lines (~{res['total_tokens']} tokens)")
    hdr_lines.append(f"Bundle: {bundle_path}")
    sys.stdout.write(format_info_box(f"[{session_name}/0] START BUNDLE", hdr_lines) + "\n")
    sys.stdout.flush()
    if not in_run_block():
        offer_clipboard_copy(f"{session_name}/0", bundle_path, ok=True, rc=0)
    return 0

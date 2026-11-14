def parse_version_from_source(source: str) -> str | None:
    m = re.search(r'^VERSION\s*=\s*["\x27]([^"\x27]+)["\x27]', source, flags=re.MULTILINE)
    return m.group(1) if m else None


def version_tuple(v: str) -> tuple[int, ...]:
    parts = []
    for p in re.split(r"[^0-9]+", v):
        if p:
            parts.append(int(p))
    return tuple(parts)


def fetch_remote_script(url: str | None = None) -> str:
    cfg_url, _ = get_setting("update_url")
    target_url = url or cfg_url
    if target_url.startswith(("http://", "https://")) and "?" not in target_url:
        target_url = f"{target_url}?t={int(time.time())}"
    req = urllib.request.Request(
        target_url,
        headers={"User-Agent": f"run_block/{VERSION}", "Cache-Control": "no-cache", "Pragma": "no-cache"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = resp.read().decode("utf-8")
    if REPO_MARKER and REPO_MARKER not in data:
        raise ValueError("downloaded file does not contain expected repository marker")
    ast.parse(data)
    return data


def cmd_check_update(url: str | None = None) -> int:
    prog = prog_name()
    try:
        remote_src = fetch_remote_script(url)
    except Exception as exc:
        sys.stderr.write(f"{prog}: failed to check for updates: {exc}\n")
        return 1
    remote_ver = parse_version_from_source(remote_src) or "unknown"
    if version_tuple(remote_ver) > version_tuple(VERSION):
        sys.stdout.write(f"{prog}: update available: {VERSION} -> {remote_ver} (run '{prog} --update')\n")
    else:
        sys.stdout.write(f"{prog} {VERSION} is up to date (remote: {remote_ver}).\n")
    return 0


def cmd_update(force: bool = False, url: str | None = None, target_path: Path | None = None) -> int:
    prog = prog_name()
    dest = target_path or Path(__file__).resolve()
    try:
        remote_src = fetch_remote_script(url)
    except Exception as exc:
        sys.stderr.write(f"{prog}: update failed: {exc}\n")
        return 1
    remote_ver = parse_version_from_source(remote_src) or "unknown"
    if not force and version_tuple(remote_ver) <= version_tuple(VERSION):
        sys.stdout.write(f"{prog} {VERSION} is already up to date.\n")
        return 0
    try:
        tmp_fd, tmp_name = tempfile.mkstemp(prefix=f".{dest.name}.", dir=str(dest.parent))
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write(remote_src)
            os.chmod(tmp_name, 0o755)
            os.replace(tmp_name, dest)
        except Exception:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
            raise
    except Exception as exc:
        sys.stderr.write(f"{prog}: could not write updated binary to {dest}: {exc}\n")
        return 1
    sys.stdout.write(f"{prog}: updated {VERSION} -> {remote_ver} ({dest})\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    prog = prog_name()
    if "-h" in args or "--help" in args:
        sys.stdout.write(usage_text())
        return 0
    if "-V" in args or "--version" in args:
        sys.stdout.write(f"{prog} {VERSION}\n")
        return 0
    if "--agents" in args or "--agents-md" in args:
        sys.stdout.write(agents_markdown(prog) + "\n")
        return 0
    if args and args[0] == "--plan":
        if len(args) != 1:
            raise SystemExit(f"{prog}: usage: {prog} --plan < script.sh")
        return cmd_plan(sys.stdin.read())
    if args and args[0] == "--clean":
        return cmd_clean(args[1:])

    if args and args[0] == "--sandbox":
        rest_sb = args[1:]
        if not any("/" in x or x.startswith("-") for x in rest_sb):
            has_session_arg = len(rest_sb) >= 2 or (
                len(rest_sb) == 1
                and rest_sb[0].lower()
                not in ("off", "0", "false", "on", "1", "true", "auto", "strict", "nonet", "no-net")
            )
            if in_run_block() or has_session_arg or sys.stdin.isatty():
                return cmd_sandbox(rest_sb)

    auto_yes = False
    sandbox_override: str | None = None
    filtered: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-y", "--yes", "--headless"):
            auto_yes = True
            i += 1
        elif a == "--no-sandbox":
            sandbox_override = "off"
            i += 1
        elif a.startswith("--sandbox="):
            sandbox_override = a.split("=", 1)[1] or "strict"
            i += 1
        elif a == "--sandbox":
            if i + 1 < len(args) and args[i + 1].lower() in ("off", "0", "false", "on", "1", "true", "auto", "strict", "nonet", "no-net"):
                sandbox_override = args[i + 1]
                i += 2
            else:
                sandbox_override = "strict"
                i += 1
        else:
            filtered.append(a)
            i += 1
    args = filtered

    if not args:
        if not sys.stdin.isatty():
            return cmd_start([], sandbox_override=sandbox_override)
        if sandbox_override is not None:
            return cmd_sandbox([sandbox_override])
        sys.stderr.write(usage_text())
        return 2

    if sandbox_override is not None and len(args) == 1 and "/" not in args[0] and not args[0].startswith("-"):
        return cmd_sandbox([sandbox_override, args[0]])

    if args[0] in ("--list", "-l"):
        if len(args) > 2:
            raise SystemExit(f"{prog}: usage: {prog} --list [session]")
        return cmd_list(args[1] if len(args) == 2 else None)

    if args[0] == "--show":
        if len(args) > 2:
            raise SystemExit(f"{prog}: usage: {prog} --show [session/step]")
        return cmd_show(args[1] if len(args) == 2 else None)

    if args[0] in ("--retry", "--rerun"):
        if len(args) > 2:
            raise SystemExit(f"{prog}: usage: {prog} --retry [-y] [session/step]")
        return cmd_retry(
            args[1] if len(args) == 2 else None, auto_yes=auto_yes, sandbox_override=sandbox_override
        )

    if args[0] == "--check-update":
        if len(args) != 1:
            raise SystemExit(f"{prog}: usage: {prog} --check-update")
        return cmd_check_update()

    if args[0] in ("--update", "--self-update"):
        force = "--force" in args[1:]
        rest = [a for a in args[1:] if a != "--force"]
        if rest:
            raise SystemExit(f"{prog}: usage: {prog} --update [--force]")
        return cmd_update(force=force)

    if args[0] in ("--start", "--bundle"):
        return cmd_start(args[1:], sandbox_override=sandbox_override)

    if args[0] == "--fix":
        if len(args) != 2:
            raise SystemExit(f"{prog}: usage: {prog} --fix [-y] <session>/<target>")
        return cmd_fix(
            args[1], sys.stdin.read(), auto_yes=auto_yes, sandbox_override=sandbox_override
        )

    if len(args) != 1 or args[0].startswith("-"):
        raise SystemExit(
            f"{prog}: usage: {prog} [-y] <session>/<step> (or pipe bundle to '{prog}' to start a session; see --help)"
        )
    return cmd_normal(
        args[0], sys.stdin.read(), auto_yes=auto_yes, sandbox_override=sandbox_override
    )


if __name__ == "__main__":
    raise SystemExit(main())

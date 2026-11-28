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
    import urllib.request

    cfg_url, _ = get_setting("update_url")
    target_url = url or cfg_url
    if target_url.startswith(("http://", "https://")) and "?" not in target_url:
        target_url = f"{target_url}?t={int(time.time())}"
    req = urllib.request.Request(
        target_url,
        headers={"User-Agent": f"run-block/{VERSION}", "Cache-Control": "no-cache", "Pragma": "no-cache"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = resp.read().decode("utf-8")
    if REPO_MARKERS and not any(m in data for m in REPO_MARKERS):
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


def _cleanup_legacy_binary_and_state(dest: Path) -> None:
    _ = default_base_dir()
    parent = dest.parent
    if (parent / "build.py").is_file() and (parent / "src" / "header.py").is_file():
        return
    if dest.name != "run_block":
        legacy_bin = parent / "run_block"
        if _is_our_installed_binary(legacy_bin):
            try:
                legacy_bin.unlink()
                sys.stdout.write(f"Removed legacy binary: {legacy_bin}\n")
            except OSError:
                pass


def cmd_update(force: bool = False, url: str | None = None, target_path: Path | None = None) -> int:
    prog = prog_name()
    dest = target_path or Path(__file__).resolve()
    if target_path is None and dest.name == "run_block":
        parent = dest.parent
        if not ((parent / "build.py").is_file() and (parent / "src" / "header.py").is_file()):
            cand_run = parent / "run"
            if not cand_run.exists() or _is_our_installed_binary(cand_run):
                dest = cand_run
    try:
        remote_src = fetch_remote_script(url)
    except Exception as exc:
        sys.stderr.write(f"{prog}: update failed: {exc}\n")
        return 1
    remote_ver = parse_version_from_source(remote_src) or "unknown"
    if not force and version_tuple(remote_ver) <= version_tuple(VERSION) and dest.is_file():
        _cleanup_legacy_binary_and_state(dest)
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
    _cleanup_legacy_binary_and_state(dest)
    sys.stdout.write(f"{prog}: updated {VERSION} -> {remote_ver} ({dest})\n")
    return 0


def _is_our_installed_binary(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:4096]
    except OSError:
        return False
    return any(marker in head for marker in REPO_MARKERS)


def cmd_uninstall(purge: bool = False, target_dir: Path | None = None) -> int:
    prog = prog_name()
    candidates: list[Path] = []
    seen_dirs: set[Path] = set()

    def _add_dir(d: Path) -> None:
        try:
            rd = d.resolve()
        except OSError:
            rd = d
        if rd in seen_dirs:
            return
        seen_dirs.add(rd)
        if (rd / "build.py").is_file() and (rd / "src" / "header.py").is_file():
            return
        names = ["run", "run_block"]
        if prog not in names:
            names.insert(0, prog)
        for name in names:
            p = d / name
            if p not in candidates:
                candidates.append(p)

    if target_dir is not None:
        _add_dir(target_dir)
    else:
        env_dir = os.environ.get("RUN_BLOCK_INSTALL_DIR", "").strip()
        if env_dir:
            _add_dir(Path(env_dir).expanduser())
        for raw_self in (sys.argv[0] if sys.argv else "", __file__):
            if raw_self:
                sp = Path(raw_self).expanduser()
                if sp.parent and sp.parent != Path("."):
                    _add_dir(sp.parent)
        if not seen_dirs:
            _add_dir(Path.home() / ".local" / "bin")

    removed_bins: list[Path] = []
    for cand in candidates:
        if _is_our_installed_binary(cand):
            try:
                cand.unlink()
                removed_bins.append(cand)
                sys.stdout.write(f"Removed: {cand}\n")
            except OSError as exc:
                sys.stderr.write(f"{prog}: failed to remove {cand}: {exc}\n")
                return 1

    if not removed_bins:
        sys.stdout.write(f"{prog}: no installed binary found.\n")

    if purge:
        state_dirs: list[Path] = [default_base_dir()]
        if not os.environ.get("RUN_BLOCK_DIR"):
            parent = _state_parent_dir()
            for name in ("run-block", "run_block"):
                sd = parent / name
                if sd not in state_dirs:
                    state_dirs.append(sd)
        for sd in state_dirs:
            try:
                if sd.is_symlink():
                    sd.unlink()
                    sys.stdout.write(f"Purged state: {sd}\n")
                elif sd.is_dir():
                    shutil.rmtree(sd)
                    sys.stdout.write(f"Purged state: {sd}\n")
            except OSError as exc:
                sys.stderr.write(f"{prog}: failed to purge state directory {sd}: {exc}\n")
                return 1
    return 0



def _extract_prompt_args(argv: list[str]) -> tuple[list[str], list[str]]:
    prog = prog_name()
    rest: list[str] = []
    prompts: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-p", "--prompt"):
            if i + 1 >= len(argv):
                raise SystemExit(f"{prog}: {a} requires an argument")
            prompts.append(argv[i + 1])
            i += 2
        elif a.startswith("--prompt="):
            prompts.append(a.split("=", 1)[1])
            i += 1
        else:
            rest.append(a)
            i += 1
    return rest, prompts


_START_FLAGS = ("--start", "--session", "--force")
_START_NEUTRAL_FLAGS = ("-y", "--yes", "--headless", "--sandbox")


def _extract_profile_arg(argv: list[str]) -> tuple[list[str], str | None]:
    prog = prog_name()
    rest: list[str] = []
    profile: str | None = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-P", "--profile"):
            if i + 1 >= len(argv) or not argv[i + 1].strip():
                raise SystemExit(f"{prog}: {a} requires an argument")
            profile = argv[i + 1].strip()
            i += 2
        elif a.startswith("--profile="):
            val = a.split("=", 1)[1].strip()
            if not val:
                raise SystemExit(f"{prog}: --profile requires an argument")
            profile = val
            i += 1
        else:
            rest.append(a)
            i += 1
    return rest, profile


def _is_session_start_args(args: list[str], prompt_args: list[str]) -> bool:
    if any(a in _START_FLAGS or a.startswith("--session=") for a in args):
        return True
    rest = [
        a
        for a in args
        if a not in _START_NEUTRAL_FLAGS and not a.startswith("--sandbox=") and a.lower() not in SANDBOX_MODE_TOKENS
    ]
    if not rest:
        return True
    return bool(prompt_args) and all(re.fullmatch(r"s\d+", a) for a in rest)


def _format_config_value(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _config_overview_lines() -> list[str]:
    cfg = config_file_path()
    proj = project_config_path()
    lines = [f"Config:  {cfg}" + ("" if cfg.is_file() else " (missing)")]
    if proj is not None:
        lines.append(f"Project: {proj}" + ("" if proj.is_file() else " (missing)"))
    ignored = project_config_ignored_keys()
    if ignored:
        lines.append(f"Ignored project keys: {', '.join(ignored)}")
    rows = effective_settings()
    width = max(len(key) for key, _, _ in rows)
    lines += ["", "Settings:"]
    for key, value, source in rows:
        shown = _format_config_value(redact_config_value(key, value)) or '""'
        lines.append(f"  {key:<{width}}  {shown}  ({source})")
    try:
        active = resolve_profile()
        active_err = ""
    except ValueError as exc:
        active, active_err = None, str(exc)
    lines += ["", "Profiles:"]
    profiles = config_profiles()
    if not profiles:
        lines.append("  (none)")
    for name, entry in profiles.items():
        mark = " *" if active is not None and active.get("name") == name else ""
        fields = " ".join(f"{k}={_format_config_value(redact_config_value(k, v))}" for k, v in entry.items())
        lines.append(f"  {name}{mark}  {fields}".rstrip())
    lines += ["", "Roles:"]
    roles = config_roles()
    if not roles:
        lines.append("  (none)")
    for role, fields_map in roles.items():
        parts = " ".join(f"{f}={_format_config_value(v)} ({src})" for f, (v, src) in fields_map.items())
        lines.append(f"  {role}  {parts}")
    lines.append("")
    if active is not None:
        lines.append(f"Active profile: {active['name']} ({active['source']})")
    elif active_err:
        lines.append(f"Active profile: error: {active_err}")
    else:
        lines.append("Active profile: (none)")
    return lines


def _edit_config_file() -> int:
    prog = prog_name()
    path = config_file_path()
    if not path.exists():
        write_user_config({})
    subprocess.run(resolve_editor_command() + [str(path)], check=False)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"{prog}: invalid config file {path}: {exc}\n")
        return 1
    if not isinstance(data, dict):
        sys.stderr.write(f"{prog}: invalid config file {path}: expected a JSON object\n")
        return 1
    os.chmod(path, 0o600)
    return 0


def cmd_config(argv: list[str]) -> int:
    prog = prog_name()
    usage = f"{prog} --config [KEY[=VALUE] | --edit | --path]"
    if len(argv) > 1:
        raise SystemExit(f"{prog}: usage: {usage}")
    if not argv:
        sys.stdout.write("\n".join(_config_overview_lines()) + "\n")
        return 0
    arg = argv[0]
    if arg == "--path":
        sys.stdout.write(f"{config_file_path()}\n")
        return 0
    mutating = arg == "--edit" or "=" in arg
    if mutating and in_run_block():
        sys.stderr.write(f"{prog}: cannot modify config.json from inside a running block\n")
        return 2
    if arg == "--edit":
        return _edit_config_file()
    if arg.startswith("-"):
        raise SystemExit(f"{prog}: usage: {usage}")
    try:
        if "=" in arg:
            key, raw_value = arg.split("=", 1)
            path = set_config_value(key, raw_value)
            action = "set" if raw_value.strip() else "unset"
            sys.stdout.write(f"{prog}: {action} {key.strip()} in {path}\n")
            return 0
        value, _source = get_config_value(arg)
    except ValueError as exc:
        raise SystemExit(f"{prog}: {exc}") from None
    if value is None:
        sys.stderr.write(f"{prog}: {arg} is not set\n")
        return 1
    shown = redact_config_value(arg.split(".")[-1], value)
    sys.stdout.write(f"{_format_config_value(shown)}\n")
    return 0


def _reject_prompt_for(command_label: str, usage: str) -> None:
    prog = prog_name()
    raise SystemExit(f"{prog}: -p/--prompt cannot be used with {command_label} (usage: {usage})")


def _parse_list_args(argv: list[str], usage: str) -> tuple[str | None, str | None]:
    session: str | None = None
    query: str | None = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--filter":
            if i + 1 >= len(argv):
                raise SystemExit(f"{prog_name()}: --filter requires an argument")
            query = argv[i + 1]
            i += 2
        elif a.startswith("--filter="):
            query = a.split("=", 1)[1]
            i += 1
        elif a.startswith("-") or session is not None:
            raise SystemExit(f"{prog_name()}: usage: {usage}")
        else:
            session = a
            i += 1
    if session is not None and query is not None:
        raise SystemExit(f"{prog_name()}: --filter cannot be combined with a session (usage: {usage})")
    return session, query


def main(argv: list[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    prog = prog_name()
    if "-h" in raw_args or "--help" in raw_args:
        sys.stdout.write(usage_text())
        return 0
    if "-V" in raw_args or "--version" in raw_args:
        sys.stdout.write(f"{prog} {VERSION}\n")
        return 0

    has_bare_sandbox_flag = False
    for idx, tok in enumerate(raw_args):
        if tok == "--sandbox":
            if idx + 1 >= len(raw_args) or raw_args[idx + 1].lower() not in SANDBOX_MODE_TOKENS:
                has_bare_sandbox_flag = True

    args, prompt_args = _extract_prompt_args(raw_args)
    args, profile_arg = _extract_profile_arg(args)
    if profile_arg is not None:
        if not _is_session_start_args(args, prompt_args):
            raise SystemExit(
                f"{prog}: -P/--profile is only supported when starting a session "
                f"(usage: <command> | {prog} [--start] -P NAME)"
            )
        try:
            resolve_profile(override=profile_arg)
        except ValueError as exc:
            raise SystemExit(f"{prog}: {exc}") from None

    if args and args[0] == "--config":
        if prompt_args:
            _reject_prompt_for("--config", f"{prog} --config [KEY[=VALUE] | --edit | --path]")
        return cmd_config(args[1:])
    if args and args[0] == "--plan":
        if prompt_args:
            _reject_prompt_for("--plan", f"{prog} --plan < script.sh")
        if len(args) != 1:
            raise SystemExit(f"{prog}: usage: {prog} --plan < script.sh")
        return cmd_plan(sys.stdin.read())
    if args and args[0] == "--bundle-plan":
        if prompt_args:
            _reject_prompt_for("--bundle-plan", f"{prog} --bundle-plan [<session>] [--json]")
        return cmd_bundle_plan(args[1:])
    if args and args[0] == "--clean":
        if prompt_args:
            _reject_prompt_for(
                "--clean",
                f"{prog} --clean [--keep N | --older-than DAYS | --max-size MB | --all] [--yes] [session...]",
            )
        return cmd_clean(args[1:])

    has_start_opt = any(
        x in _START_FLAGS or x.startswith("--session=")
        for x in args
    )
    if args and args[0] == "--sandbox" and not has_start_opt:
        rest_sb = args[1:]
        if not any("/" in x or x.startswith("-") for x in rest_sb):
            has_session_arg = len(rest_sb) >= 2 or (
                len(rest_sb) == 1 and rest_sb[0].lower() not in SANDBOX_MODE_TOKENS
            )
            if in_run_block() or has_session_arg or has_bare_sandbox_flag or (
                sys.stdin.isatty() and not prompt_args
            ):
                if prompt_args:
                    _reject_prompt_for("--sandbox", f"{prog} --sandbox [off|strict|nonet] [session]")
                return cmd_sandbox(rest_sb)

    auto_yes = False
    headless_flag = False
    sandbox_override: str | None = None
    filtered: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-y", "--yes"):
            auto_yes = True
            i += 1
        elif a == "--headless":
            auto_yes = True
            headless_flag = True
            i += 1
        elif a.startswith("--sandbox="):
            sandbox_override = a.split("=", 1)[1] or "strict"
            i += 1
        elif a == "--sandbox":
            if i + 1 < len(args) and args[i + 1].lower() in SANDBOX_MODE_TOKENS:
                sandbox_override = args[i + 1]
                i += 2
            else:
                sandbox_override = "strict"
                i += 1
        elif (
            len(a) > 2
            and a.startswith("-")
            and not a.startswith("--")
            and set(a[1:]).issubset({"r", "c", "y"})
            and ("r" in a[1:] or "c" in a[1:])
            and (i == 0 or args[i - 1] not in ("-m", "--filter", "--session"))
        ):
            if "y" in a[1:]:
                auto_yes = True
            if "r" in a[1:]:
                filtered.append("-r")
            if "c" in a[1:]:
                filtered.append("-c")
            i += 1
        else:
            filtered.append(a)
            i += 1
    args = filtered
    if headless_flag:
        return _run_with_headless_env(
            lambda: _dispatch_cli(args, prompt_args, prog, auto_yes, sandbox_override, has_start_opt, has_bare_sandbox_flag, profile=profile_arg)
        )
    return _dispatch_cli(args, prompt_args, prog, auto_yes, sandbox_override, has_start_opt, has_bare_sandbox_flag, profile=profile_arg)


def _run_with_headless_env(fn) -> int:
    prev = os.environ.get("RUN_BLOCK_HEADLESS")
    os.environ["RUN_BLOCK_HEADLESS"] = "1"
    try:
        return fn()
    finally:
        if prev is None:
            os.environ.pop("RUN_BLOCK_HEADLESS", None)
        else:
            os.environ["RUN_BLOCK_HEADLESS"] = prev


def _dispatch_cli(
    args: list[str],
    prompt_args: list[str],
    prog: str,
    auto_yes: bool,
    sandbox_override: str | None,
    has_start_opt: bool,
    has_bare_sandbox_flag: bool,
    profile: str | None = None,
) -> int:

    if not args:
        if sandbox_override is not None and not has_start_opt:
            if in_run_block() or has_bare_sandbox_flag or (sys.stdin.isatty() and not prompt_args):
                if prompt_args:
                    _reject_prompt_for("--sandbox", f"{prog} --sandbox [off|strict|nonet] [session]")
                return cmd_sandbox([sandbox_override])
        return cmd_start([], sandbox_override=sandbox_override, prompt=prompt_args, profile=profile)

    if sandbox_override is not None and len(args) == 1 and "/" not in args[0] and not args[0].startswith("-"):
        if prompt_args:
            _reject_prompt_for("--sandbox", f"{prog} --sandbox [off|strict|nonet] [session]")
        return cmd_sandbox([sandbox_override, args[0]])

    if args[0] in ("--list", "-l"):
        list_usage = f"{prog} --list [session | --filter TEXT]"
        if prompt_args:
            _reject_prompt_for(args[0], list_usage)
        list_session, list_query = _parse_list_args(args[1:], list_usage)
        return cmd_list(list_session, query=list_query)

    if args[0] == "--done":
        done_usage = f"{prog} --done [-y] [session] [-m NOTE]"
        if prompt_args:
            _reject_prompt_for("--done", done_usage)
        done_note: str | None = None
        done_session: str | None = None
        j = 1
        while j < len(args):
            tok = args[j]
            if tok == "-m":
                if j + 1 >= len(args):
                    raise SystemExit(f"{prog}: -m requires an argument")
                done_note = args[j + 1]
                j += 2
            elif tok.startswith("-") or done_session is not None:
                raise SystemExit(f"{prog}: usage: {done_usage}")
            else:
                done_session = tok
                j += 1
        return cmd_done(done_session, note=done_note, auto_yes=auto_yes)

    if args[0] == "--show":
        show_usage = f"{prog} --show [session[/step]] [--part N | --script | --out]"
        if prompt_args:
            _reject_prompt_for("--show", show_usage)
        only_flags = [a for a in args[1:] if a in ("--script", "--out")]
        show_args = [a for a in args[1:] if a not in ("--script", "--out")]
        show_rest, show_part = parse_part_option(show_args, show_usage)
        if len(show_rest) > 1 or len(set(only_flags)) > 1 or (only_flags and show_part is not None):
            raise SystemExit(f"{prog}: usage: {show_usage}")
        return cmd_show(
            show_rest[0] if show_rest else None,
            part=show_part,
            only=only_flags[0][2:] if only_flags else None,
        )

    if args[0] == "--retry":
        if prompt_args:
            _reject_prompt_for("--retry", f"{prog} --retry [-y] [session[/step]]")
        if len(args) > 2:
            raise SystemExit(f"{prog}: usage: {prog} --retry [-y] [session[/step]]")
        return cmd_retry(
            args[1] if len(args) == 2 else None, auto_yes=auto_yes, sandbox_override=sandbox_override
        )

    if args[0] == "--update":
        update_usage = f"{prog} --update [--check | --force]"
        if prompt_args:
            _reject_prompt_for("--update", update_usage)
        check_only = "--check" in args[1:]
        force = "--force" in args[1:]
        rest = [a for a in args[1:] if a not in ("--check", "--force")]
        if rest or (check_only and force):
            raise SystemExit(f"{prog}: usage: {update_usage}")
        if check_only:
            return cmd_check_update()
        return cmd_update(force=force)

    if args[0] == "--uninstall":
        if prompt_args:
            _reject_prompt_for("--uninstall", f"{prog} --uninstall [--purge]")
        purge = "--purge" in args[1:]
        rest = [a for a in args[1:] if a != "--purge"]
        if rest:
            raise SystemExit(f"{prog}: usage: {prog} --uninstall [--purge]")
        return cmd_uninstall(purge=purge)

    if args[0] == "--start":
        return cmd_start(args[1:], sandbox_override=sandbox_override, prompt=prompt_args, profile=profile)

    if args[0] in ("-r", "--run", "-c", "--clipboard") or args[0].startswith("--run="):
        run_usage = f"{prog} --run [-c] [-y] [session]"
        if prompt_args:
            _reject_prompt_for(args[0].split("=", 1)[0], run_usage)
        has_run = False
        from_clipboard = False
        run_session: str | None = None
        for tok in args:
            if tok in ("-r", "--run"):
                has_run = True
            elif tok.startswith("--run="):
                has_run = True
                val = tok.split("=", 1)[1]
                if not val or run_session is not None:
                    raise SystemExit(f"{prog}: usage: {run_usage}")
                run_session = val
            elif tok in ("-c", "--clipboard"):
                from_clipboard = True
            elif tok.startswith("-") or run_session is not None:
                raise SystemExit(f"{prog}: usage: {run_usage}")
            else:
                run_session = tok
        if not has_run:
            raise SystemExit(f"{prog}: -c/--clipboard requires -r/--run (usage: {run_usage})")
        return cmd_run_reply(
            run_session,
            auto_yes=auto_yes,
            sandbox_override=sandbox_override,
            from_clipboard=from_clipboard,
        )

    if args[0] == "--fix":
        if prompt_args:
            _reject_prompt_for("--fix", f"{prog} --fix [-y] <session>/<target>")
        if len(args) != 2:
            raise SystemExit(f"{prog}: usage: {prog} --fix [-y] <session>/<target>")
        return cmd_fix(
            args[1], sys.stdin.read(), auto_yes=auto_yes, sandbox_override=sandbox_override
        )

    if args[0] in ("--session", "--force") or args[0].startswith("--session="):
        return cmd_start(args, sandbox_override=sandbox_override, prompt=prompt_args, profile=profile)

    if prompt_args:
        if len(args) == 1 and "/" in args[0] and not args[0].startswith("-"):
            _reject_prompt_for(args[0], f"{prog} [-y] <session>/<step>")
        return cmd_start(args, sandbox_override=sandbox_override, prompt=prompt_args, profile=profile)

    if len(args) != 1 or args[0].startswith("-"):
        raise SystemExit(
            f"{prog}: usage: {prog} [-y] <session>/<step> (or pipe bundle to '{prog}' to start a session; see --help)"
        )
    return cmd_normal(
        args[0], sys.stdin.read(), auto_yes=auto_yes, sandbox_override=sandbox_override
    )


if __name__ == "__main__":
    raise SystemExit(main())

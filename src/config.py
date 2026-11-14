def prog_name() -> str:
    raw = Path(sys.argv[0]).name if sys.argv and sys.argv[0] else "run_block"
    for suf in (".py", ".cmd", ".bat", ".exe"):
        if raw.lower().endswith(suf) and len(raw) > len(suf):
            raw = raw[:-len(suf)]
            break
    return raw or "run_block"


def _os_default_base_dir(prog: str | None = None) -> Path:
    name = prog or prog_name()
    if os.name == "nt":
        return Path(tempfile.gettempdir()) / name
    return Path("/tmp") / name


def get_setting(key: str, prog: str | None = None) -> tuple[str, str]:
    """Returns (value, source) where source is 'env' or 'default'."""
    if key == "base_dir":
        if os.environ.get("RUN_BLOCK_DIR"):
            return os.environ["RUN_BLOCK_DIR"], "env"
        return str(_os_default_base_dir(prog)), "default"
    if key == "work_dir":
        if os.environ.get("RUN_BLOCK_CWD"):
            return os.environ["RUN_BLOCK_CWD"], "env"
        return "auto", "default"
    if key == "clipboard":
        if os.environ.get("RUN_BLOCK_NO_CLIPBOARD") == "1" or os.environ.get("RUN_BLOCK_HEADLESS") == "1":
            return "never", "env"
        if os.environ.get("RUN_BLOCK_CLIPBOARD"):
            return os.environ["RUN_BLOCK_CLIPBOARD"].strip().lower(), "env"
        return "prompt", "default"
    if key == "token_stats":
        if os.environ.get("RUN_BLOCK_TOKEN_STATS"):
            v = os.environ["RUN_BLOCK_TOKEN_STATS"].strip().lower()
            return ("false" if v in ("0", "false", "no", "off") else "true"), "env"
        return "true", "default"
    if key == "shell":
        if os.environ.get("RUN_BLOCK_SHELL"):
            return os.environ["RUN_BLOCK_SHELL"].strip(), "env"
        return ("pwsh" if os.name == "nt" else "bash"), "default"
    if key == "editor":
        if os.environ.get("RUN_BLOCK_EDITOR"):
            return os.environ["RUN_BLOCK_EDITOR"].strip(), "env"
        return "auto", "default"
    if key == "safety_disable":
        if os.environ.get("RUN_BLOCK_SAFETY_DISABLE") is not None:
            return os.environ["RUN_BLOCK_SAFETY_DISABLE"].strip(), "env"
        return "", "default"
    if key == "safety_rules":
        if os.environ.get("RUN_BLOCK_SAFETY_RULES") is not None:
            return os.environ["RUN_BLOCK_SAFETY_RULES"].strip(), "env"
        return "", "default"
    if key == "sandbox":
        if os.environ.get("RUN_BLOCK_SANDBOX") is not None and os.environ["RUN_BLOCK_SANDBOX"].strip():
            return normalize_sandbox_mode(os.environ["RUN_BLOCK_SANDBOX"].strip()), "env"
        return "off", "default"
    if key == "approve_cmd":
        if os.environ.get("RUN_BLOCK_APPROVE_CMD"):
            return os.environ["RUN_BLOCK_APPROVE_CMD"].strip(), "env"
        return "", "default"
    if key == "update_url":
        if os.environ.get("RUN_BLOCK_UPDATE_URL"):
            return os.environ["RUN_BLOCK_UPDATE_URL"].strip(), "env"
        return DEFAULT_UPDATE_URL, "default"
    raise KeyError(f"unknown setting: {key}")


def _is_powershell(shell_bin: str | None = None) -> bool:
    sh = shell_bin if shell_bin is not None else get_setting("shell")[0]
    name = Path(sh).name.lower()
    for suf in (".exe", ".cmd", ".bat"):
        if name.endswith(suf):
            name = name[:-len(suf)]
            break
    return name in ("pwsh", "powershell")


def _script_ext(shell_bin: str | None = None) -> str:
    return ".ps1" if _is_powershell(shell_bin) else ".sh"


def _find_step_script(sdir: Path, step: str, shell_bin: str | None = None) -> Path:
    for ext in (".sh", ".ps1"):
        p = sdir / f"{step}{ext}"
        if p.exists():
            return p
    return sdir / f"{step}{_script_ext(shell_bin)}"


def _iter_session_scripts(sdir: Path) -> list[Path]:
    by_stem: dict[str, Path] = {}
    for ext in (".sh", ".ps1"):
        for p in sdir.glob(f"*{ext}"):
            by_stem.setdefault(p.stem, p)
    return [by_stem[k] for k in sorted(by_stem.keys(), key=_step_sort_key)]


def default_base_dir(prog: str | None = None) -> Path:
    val, _ = get_setting("base_dir", prog=prog)
    return Path(val)


BASE_DIR = default_base_dir()


def usage_text() -> str:
    prog = prog_name()
    bdir = default_base_dir(prog)
    return (__doc__ or "").format(prog=prog, base_dir=bdir)


def _git_toplevel_or_cwd() -> Path:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
            check=False,
        )
        if r.returncode == 0 and r.stdout.strip():
            top = Path(r.stdout.strip())
            if top.is_dir():
                return top.resolve()
    except Exception:
        pass
    return Path.cwd().resolve()


BUNDLE_HEADER_RE = re.compile(r"^([A-Za-z][A-Za-z0-9-]*(?:\s+[A-Za-z0-9-]+)?):\s*(.*)$")


def parse_bundle_headers(session_dir: Path | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if session_dir is None:
        return headers
    bundle_file = session_dir / "0.txt"
    if not bundle_file.is_file():
        return headers
    try:
        with bundle_file.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith("====="):
                    break
                m = BUNDLE_HEADER_RE.match(stripped)
                if not m:
                    break
                key = re.sub(r"\s+", "-", m.group(1).strip().lower())
                headers[key] = m.group(2).strip()
    except OSError:
        pass
    return headers


def _session_bundle_workdir(session_dir: Path | None) -> Path | None:
    headers = parse_bundle_headers(session_dir)
    raw = headers.get("workdir") or headers.get("work-dir") or ""
    if raw:
        try:
            p = Path(raw)
            if p.is_dir():
                return p.resolve()
        except OSError:
            pass
    return None


def normalize_sandbox_mode(raw: str) -> str:
    v = raw.strip().lower()
    if v in ("", "0", "off", "false", "no", "none", "disable", "disabled"):
        return "off"
    if v in ("1", "on", "true", "yes", "auto", "strict", "bwrap", "seatbelt", "sandbox-exec"):
        return "strict"
    if v in ("nonet", "no-net", "offline", "bwrap-nonet", "seatbelt-nonet"):
        return "nonet"
    return raw.strip()


def get_work_dir(session_dir: Path | None = None) -> Path:
    val, _ = get_setting("work_dir")
    if val.lower() == "cwd":
        return Path.cwd()
    if val.lower() != "auto":
        return Path(val).expanduser()
    sess_wdir = _session_bundle_workdir(session_dir)
    if sess_wdir is not None:
        return sess_wdir
    return _git_toplevel_or_cwd()


def get_sandbox_mode(session_dir: Path | None = None, override: str | None = None) -> str:
    if override is not None and override.strip():
        return normalize_sandbox_mode(override)
    if os.environ.get("RUN_BLOCK_SANDBOX") is not None and os.environ["RUN_BLOCK_SANDBOX"].strip():
        return normalize_sandbox_mode(os.environ["RUN_BLOCK_SANDBOX"])
    if session_dir is not None:
        headers = parse_bundle_headers(session_dir)
        raw_sb = headers.get("sandbox") or ""
        if raw_sb:
            mode_token = raw_sb.split()[0]
            return normalize_sandbox_mode(mode_token)
    val, _ = get_setting("sandbox")
    return normalize_sandbox_mode(val)


def clipboard_mode() -> str:
    val, _ = get_setting("clipboard")
    if val in ("never", "off", "0", "false", "no"):
        return "never"
    if val in ("auto", "always"):
        return "auto"
    return "prompt"


def no_clipboard() -> bool:
    return clipboard_mode() == "never"


def in_run_block() -> bool:
    return os.environ.get("IN_RUN_BLOCK") == "1"

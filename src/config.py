def prog_name() -> str:
    raw = Path(sys.argv[0]).name if sys.argv and sys.argv[0] else "run_block"
    for suf in (".py", ".cmd", ".bat", ".exe"):
        if raw.lower().endswith(suf) and len(raw) > len(suf):
            raw = raw[:-len(suf)]
            break
    return raw or "run_block"


def config_file_path() -> Path:
    env_cfg = os.environ.get("RUN_BLOCK_CONFIG")
    if env_cfg:
        return Path(env_cfg).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    xdg_path = (Path(xdg).expanduser() if xdg else (Path.home() / ".config")) / "run_block" / "config"
    if os.name == "nt" and not xdg_path.exists():
        appdata = os.environ.get("APPDATA")
        if appdata:
            win_path = Path(appdata) / "run_block" / "config"
            if win_path.exists():
                return win_path
    return xdg_path


def parse_config_file(path: Path | None = None) -> dict[str, str]:
    target = path if path is not None else config_file_path()
    if not target.is_file():
        return {}
    out: dict[str, str] = {}
    try:
        for raw_line in target.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or line.startswith(";"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            key = k.strip().lower()
            val = v.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                val = val[1:-1]
            else:
                val = re.sub(r"\s+#.*$", "", val).strip()
            if key:
                out[key] = val
    except Exception:
        return {}
    return out


def _os_default_base_dir(prog: str | None = None) -> Path:
    name = prog or prog_name()
    if os.name == "nt":
        return Path(tempfile.gettempdir()) / name
    return Path("/tmp") / name


def get_setting(key: str, prog: str | None = None) -> tuple[str, str]:
    """Returns (value, source) where source is 'env', 'config', or 'default'."""
    cfg = parse_config_file()
    if key == "base_dir":
        if os.environ.get("RUN_BLOCK_DIR"):
            return os.environ["RUN_BLOCK_DIR"], "env"
        if "base_dir" in cfg and cfg["base_dir"]:
            return str(Path(cfg["base_dir"]).expanduser()), "config"
        return str(_os_default_base_dir(prog)), "default"
    if key == "work_dir":
        if os.environ.get("RUN_BLOCK_CWD"):
            return os.environ["RUN_BLOCK_CWD"], "env"
        if "work_dir" in cfg and cfg["work_dir"]:
            return cfg["work_dir"], "config"
        return "auto", "default"
    if key == "clipboard":
        if os.environ.get("RUN_BLOCK_NO_CLIPBOARD") == "1":
            return "never", "env"
        if os.environ.get("RUN_BLOCK_CLIPBOARD"):
            return os.environ["RUN_BLOCK_CLIPBOARD"].strip().lower(), "env"
        if "clipboard" in cfg and cfg["clipboard"]:
            return cfg["clipboard"].strip().lower(), "config"
        return "prompt", "default"
    if key == "token_stats":
        if os.environ.get("RUN_BLOCK_TOKEN_STATS"):
            v = os.environ["RUN_BLOCK_TOKEN_STATS"].strip().lower()
            return ("false" if v in ("0", "false", "no", "off") else "true"), "env"
        if "token_stats" in cfg and cfg["token_stats"]:
            v = cfg["token_stats"].strip().lower()
            return ("false" if v in ("0", "false", "no", "off") else "true"), "config"
        return "true", "default"
    if key == "shell":
        if os.environ.get("RUN_BLOCK_SHELL"):
            return os.environ["RUN_BLOCK_SHELL"].strip(), "env"
        if "shell" in cfg and cfg["shell"]:
            return cfg["shell"].strip(), "config"
        return "bash", "default"
    if key == "editor":
        if os.environ.get("RUN_BLOCK_EDITOR"):
            return os.environ["RUN_BLOCK_EDITOR"].strip(), "env"
        if "editor" in cfg and cfg["editor"]:
            return cfg["editor"].strip(), "config"
        return "auto", "default"
    if key == "safety_disable":
        if os.environ.get("RUN_BLOCK_SAFETY_DISABLE") is not None:
            return os.environ["RUN_BLOCK_SAFETY_DISABLE"].strip(), "env"
        if "safety_disable" in cfg:
            return cfg["safety_disable"].strip(), "config"
        return "", "default"
    if key == "safety_rules":
        if os.environ.get("RUN_BLOCK_SAFETY_RULES") is not None:
            return os.environ["RUN_BLOCK_SAFETY_RULES"].strip(), "env"
        custom = [f"{k[len('safety_rule.'):]}={v}" for k, v in cfg.items() if k.startswith("safety_rule.") and v]
        if custom:
            return "; ".join(custom), "config"
        return "", "default"
    if key == "update_url":
        if os.environ.get("RUN_BLOCK_UPDATE_URL"):
            return os.environ["RUN_BLOCK_UPDATE_URL"].strip(), "env"
        if "update_url" in cfg and cfg["update_url"]:
            return cfg["update_url"].strip(), "config"
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


def default_config_template(prog: str | None = None) -> str:
    cmd = prog or prog_name()
    bdir = _os_default_base_dir(cmd)
    lines = [
        f"# {cmd} configuration file",
        "# Lines starting with # are comments. Environment variables override these settings.",
        "",
        "# Base directory where session scripts (<step>.sh) and logs (<step>.txt) are stored:",
        f"base_dir = {bdir}",
        "",
        "# Working directory for executing blocks:",
        "#   auto -> current Git repository root (or current directory if outside Git)",
        "#   cwd  -> always use the current working directory ($PWD)",
        "#   /path/to/dir -> explicit directory path",
        "work_dir = auto",
        "",
        "# Clipboard behavior after a block finishes:",
        "#   prompt -> press Enter to copy output to clipboard or Esc to skip (default)",
        "#   auto   -> copy output to clipboard automatically without prompting",
        "#   never  -> do not offer or copy to clipboard",
        "clipboard = prompt",
        "",
        "# Show output size in bytes and estimated token counts (Claude / GPT / Gemini):",
        "token_stats = true",
        "",
        "# Shell executable used for syntax checking and running blocks (e.g. bash, sh, pwsh):",
        "shell = bash",
        "",
        "# Terminal editor/viewer opened when pressing 'v' or 'e' in BLOCK PLAN:",
        "#   auto -> uses $VISUAL, $EDITOR, nano, less, or vi",
        "editor = auto",
        "",
        "# Safety scanner customization:",
        "#   safety_disable = git-push, net-write, privilege-system",
        "#   safety_rule.<category> = <regex>  (adds a new category or overrides a built-in one)",
        "# safety_disable = ",
        "",
    ]
    return "\n".join(lines)


def cmd_show_config() -> int:
    prog = prog_name()
    cfg_path = config_file_path()
    exists_str = "exists" if cfg_path.is_file() else "not created yet (run --init-config)"
    sys.stdout.write(f"Config file: {cfg_path} ({exists_str})\n\n")
    sys.stdout.write("Active settings:\n")
    for k in ("base_dir", "work_dir", "clipboard", "token_stats", "shell", "editor", "safety_disable", "safety_rules"):
        val, src = get_setting(k, prog=prog)
        if k in ("safety_disable", "safety_rules") and not val and src == "default":
            continue
        sys.stdout.write(f"  {k:<14} = {val}  (from {src})\n")
    return 0


def cmd_init_config(force: bool = False) -> int:
    prog = prog_name()
    cfg_path = config_file_path()
    if cfg_path.exists() and not force:
        sys.stderr.write(f"{prog}: config file already exists at {cfg_path} (use --force to overwrite)\n")
        return 2
    cfg_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    cfg_path.write_text(default_config_template(prog), encoding="utf-8")
    sys.stdout.write(f"{prog}: wrote default configuration to {cfg_path}\n")
    return 0


def usage_text() -> str:
    prog = prog_name()
    bdir = default_base_dir(prog)
    cpath = config_file_path()
    return (__doc__ or "").format(prog=prog, base_dir=bdir, config_path=cpath)


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


def _session_bundle_workdir(session_dir: Path | None) -> Path | None:
    if session_dir is None:
        return None
    bundle_file = session_dir / "0.txt"
    if not bundle_file.is_file():
        return None
    try:
        with bundle_file.open(encoding="utf-8", errors="replace") as f:
            for _ in range(10):
                line = f.readline()
                if not line or line.startswith("====="):
                    break
                if line.startswith("Workdir:"):
                    raw = line.split(":", 1)[1].strip()
                    if raw:
                        p = Path(raw)
                        if p.is_dir():
                            return p.resolve()
    except OSError:
        pass
    return None


def get_work_dir(session_dir: Path | None = None) -> Path:
    val, _ = get_setting("work_dir")
    if val.lower() == "cwd":
        return Path.cwd()
    if val.lower() != "auto":
        return Path(val).expanduser()
    base_root = _git_toplevel_or_cwd()
    sess_wdir = _session_bundle_workdir(session_dir)
    if sess_wdir is not None and (sess_wdir == base_root or base_root in sess_wdir.parents):
        return sess_wdir
    return base_root


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

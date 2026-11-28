CHILD_PAGER_ENV_VARS = (
    "PAGER",
    "GIT_PAGER",
    "GH_PAGER",
    "MANPAGER",
    "SYSTEMD_PAGER",
    "BAT_PAGER",
    "AWS_PAGER",
    "PSQL_PAGER",
    "DELTA_PAGER",
)
_PAGER_PASSTHROUGH_VALUES = ("0", "false", "no", "off", "inherit", "keep", "passthrough")


def prog_name() -> str:
    raw = Path(sys.argv[0]).name if sys.argv and sys.argv[0] else "run"
    if raw.lower().endswith(".py") and len(raw) > 3:
        raw = raw[:-3]
    if not raw or raw.startswith("-"):
        return "run"
    return raw


def _state_parent_dir() -> Path:
    xdg_state = os.environ.get("XDG_STATE_HOME", "").strip()
    if xdg_state:
        return Path(xdg_state).expanduser()
    return Path.home() / ".local" / "state"


def _migrate_state_dir(parent: Path) -> Path:
    target = parent / "run-block"
    legacy = parent / "run_block"
    if os.environ.get("RUN_BLOCK_DIR"):
        return target
    try:
        if legacy.is_symlink():
            if not in_run_block():
                legacy.unlink(missing_ok=True)
            return target
        if legacy.is_dir() and not target.exists():
            os.replace(legacy, target)
            if in_run_block():
                try:
                    os.symlink("run-block", legacy)
                except OSError:
                    pass
    except OSError:
        pass
    return target


def _os_default_base_dir(prog: str | None = None, *, migrate: bool = True) -> Path:
    _ = prog
    parent = _state_parent_dir()
    return _migrate_state_dir(parent) if migrate else (parent / "run-block")


CONFIG_DIR_NAME = "run-block"
CONFIG_FILE_NAME = "config.json"
LEGACY_CONFIG_FILE_NAME = "models.json"
PROJECT_CONFIG_FILE_NAME = ".run-block.json"

PROVIDER_API_KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}
GENERIC_API_KEY_ENV = "RUN_BLOCK_API_KEY"
PROVIDER_API_KEY_ENV_VARS = (*PROVIDER_API_KEY_ENV.values(), GENERIC_API_KEY_ENV)
ROLE_NAMES = ("plan", "design", "work", "review", "law")
PROFILE_FIELDS = ("provider", "model", "base_url", "api_key_env", "api_key_cmd", "max_tokens", "thinking", "cache")
ROLE_FIELDS = ("profile", "mode", "max_steps")
CACHE_MODES = ("auto", "system", "off")
_FALSY_TOKENS = ("0", "false", "no", "off")
_PROFILE_NAME_RE = re.compile(r"[A-Za-z0-9_-]+")
_SECRET_CONFIG_KEY_RE = re.compile(r"(?:^|_)(?:api_key|api_key_cmd|secret|password|token|credentials?)$", re.I)


def _norm_text(raw: str) -> str | None:
    return raw.strip()


def _norm_lower(raw: str) -> str | None:
    return raw.strip().lower()


def _norm_path(raw: str) -> str | None:
    return str(Path(raw.strip()).expanduser())


def _norm_bool(raw: str) -> str | None:
    return "false" if raw.strip().lower() in _FALSY_TOKENS else "true"


def _norm_pager(raw: str) -> str | None:
    val = raw.strip()
    return "" if val.lower() in _PAGER_PASSTHROUGH_VALUES else val


def _norm_sandbox(raw: str) -> str | None:
    return normalize_sandbox_mode(raw.strip())


def _norm_fix_attempts(raw: str) -> str | None:
    try:
        return str(max(1, int(raw.strip())))
    except ValueError:
        return None


def _norm_nonneg_int(raw: str) -> str | None:
    try:
        val = int(raw.strip())
    except ValueError:
        return None
    return str(val) if val >= 0 else None


def _norm_nonneg_float(raw: str) -> str | None:
    try:
        val = float(raw.strip())
    except ValueError:
        return None
    return str(val) if val >= 0 else None


def _norm_cache(raw: str) -> str | None:
    val = raw.strip().lower()
    return val if val in CACHE_MODES else None


# key -> (environment variable, default, normalizer, empty env value counts as set)
_SETTING_SPECS: dict[str, tuple] = {
    "base_dir": ("RUN_BLOCK_DIR", None, _norm_path, False),
    "work_dir": ("RUN_BLOCK_CWD", "auto", _norm_text, False),
    "clipboard": ("RUN_BLOCK_CLIPBOARD", "prompt", _norm_lower, False),
    "token_stats": ("RUN_BLOCK_TOKEN_STATS", "true", _norm_bool, False),
    "progress": ("RUN_BLOCK_PROGRESS", "true", _norm_bool, False),
    "pager": ("RUN_BLOCK_PAGER", "cat", _norm_pager, False),
    "shell": ("RUN_BLOCK_SHELL", "bash", _norm_text, False),
    "editor": ("RUN_BLOCK_EDITOR", "auto", _norm_text, False),
    "safety_disable": ("RUN_BLOCK_SAFETY_DISABLE", "", _norm_text, True),
    "safety_rules": ("RUN_BLOCK_SAFETY_RULES", "", _norm_text, True),
    "sandbox": ("RUN_BLOCK_SANDBOX", "off", _norm_sandbox, False),
    "approve_cmd": ("RUN_BLOCK_APPROVE_CMD", "", _norm_text, False),
    "max_fix_attempts": ("RUN_BLOCK_MAX_FIX_ATTEMPTS", "2", _norm_fix_attempts, False),
    "max_state_mb": ("RUN_BLOCK_MAX_STATE_MB", "100", _norm_nonneg_float, False),
    "bundle_max_tokens": ("RUN_BLOCK_BUNDLE_MAX_TOKENS", "100000", _norm_nonneg_int, False),
    "fragment_max_tokens": ("RUN_BLOCK_FRAGMENT_MAX_TOKENS", "20000", _norm_nonneg_int, False),
    "update_url": ("RUN_BLOCK_UPDATE_URL", DEFAULT_UPDATE_URL, _norm_text, False),
    "model": ("RUN_BLOCK_MODEL", "", _norm_text, False),
    "cache": ("RUN_BLOCK_CACHE", "auto", _norm_cache, False),
    "compact_tokens": ("RUN_BLOCK_COMPACT_TOKENS", "120000", _norm_nonneg_int, False),
    "max_steps": ("RUN_BLOCK_MAX_STEPS", "", _norm_nonneg_int, False),
}
SETTING_KEYS = tuple(_SETTING_SPECS)
# Repository-local .run-block.json may only tune non-privileged behavior: no hooks,
# commands, safety switches, sandbox, paths, update source, or model profiles.
PROJECT_SETTING_ALLOWLIST = frozenset({
    "clipboard",
    "token_stats",
    "progress",
    "pager",
    "max_fix_attempts",
    "max_state_mb",
    "bundle_max_tokens",
    "fragment_max_tokens",
    "model",
    "cache",
    "compact_tokens",
    "max_steps",
})
PROJECT_CONFIG_ALLOWLIST = PROJECT_SETTING_ALLOWLIST | frozenset({"default_profile", "roles"})

_CONFIG_JSON_CACHE: dict[str, tuple[tuple[int, int, int], dict[str, object]]] = {}
_PROJECT_ROOT_CACHE: dict[tuple[str, str], Path] = {}


def _config_home() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
    return Path(xdg).expanduser() if xdg else Path.home() / ".config"


def config_file_path() -> Path:
    """Returns RUN_BLOCK_CONFIG, else run-block/config.json (falling back to an existing models.json)."""
    override = os.environ.get("RUN_BLOCK_CONFIG", "").strip()
    if override:
        return Path(override).expanduser()
    cfg_dir = _config_home() / CONFIG_DIR_NAME
    primary = cfg_dir / CONFIG_FILE_NAME
    legacy = cfg_dir / LEGACY_CONFIG_FILE_NAME
    if not primary.exists() and legacy.is_file():
        return legacy
    return primary


def project_config_path() -> Path | None:
    raw_cwd = os.environ.get("RUN_BLOCK_CWD", "").strip()
    try:
        cwd = Path.cwd()
    except OSError:
        return None
    cache_key = (str(cwd), raw_cwd)
    root = _PROJECT_ROOT_CACHE.get(cache_key)
    if root is None:
        mode = raw_cwd.lower()
        if raw_cwd and mode not in ("auto", "cwd"):
            root = Path(raw_cwd).expanduser()
        elif mode == "cwd":
            root = cwd
        else:
            root = _git_toplevel_or_cwd()
        _PROJECT_ROOT_CACHE[cache_key] = root
    return root / PROJECT_CONFIG_FILE_NAME


def _load_json_object(path: Path | None) -> dict[str, object]:
    if path is None or not path.is_file():
        return {}
    try:
        st = path.stat()
    except OSError:
        return {}
    sig = (st.st_ino, st.st_mtime_ns, st.st_size)
    cached = _CONFIG_JSON_CACHE.get(str(path))
    if cached is not None and cached[0] == sig:
        return cached[1]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"{prog_name()}: invalid config file {path}: {exc}") from None
    if not isinstance(data, dict):
        raise SystemExit(f"{prog_name()}: invalid config file {path}: expected a JSON object")
    _CONFIG_JSON_CACHE[str(path)] = (sig, data)
    return data


def user_config() -> dict[str, object]:
    return _load_json_object(config_file_path())


def _raw_project_config() -> dict[str, object]:
    return _load_json_object(project_config_path())


def project_config() -> dict[str, object]:
    """Returns .run-block.json restricted to PROJECT_CONFIG_ALLOWLIST."""
    return {k: v for k, v in _raw_project_config().items() if k in PROJECT_CONFIG_ALLOWLIST}


def project_config_ignored_keys() -> list[str]:
    return sorted(k for k in _raw_project_config() if k not in PROJECT_CONFIG_ALLOWLIST)


def _config_layers(key: str) -> list[tuple[str, dict[str, object]]]:
    layers: list[tuple[str, dict[str, object]]] = []
    if key in PROJECT_CONFIG_ALLOWLIST:
        layers.append(("project", project_config()))
    layers.append(("config", user_config()))
    return layers


def _config_scalar(value: object) -> str | None:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value
    return None


def get_setting(key: str, prog: str | None = None, *, migrate: bool = True) -> tuple[str, str]:
    """Returns (value, source) resolved as env > project (.run-block.json) > config (config.json) > default."""
    spec = _SETTING_SPECS.get(key)
    if spec is None:
        raise KeyError(f"unknown setting: {key}")
    env_name, default, normalize, keep_empty = spec
    if key == "clipboard" and (
        os.environ.get("RUN_BLOCK_NO_CLIPBOARD") == "1" or os.environ.get("RUN_BLOCK_HEADLESS") == "1"
    ):
        return "never", "env"
    raw_env = os.environ.get(env_name)
    if raw_env is not None and (keep_empty or raw_env.strip()):
        val = normalize(raw_env)
        if val is not None:
            return val, "env"
    for source, data in _config_layers(key):
        raw_cfg = _config_scalar(data.get(key))
        if raw_cfg is not None and (keep_empty or raw_cfg.strip()):
            val = normalize(raw_cfg)
            if val is not None:
                return val, source
    if key == "base_dir":
        return str(_os_default_base_dir(prog, migrate=migrate)), "default"
    return str(default), "default"


def effective_settings() -> list[tuple[str, str, str]]:
    return [(key, *get_setting(key, migrate=False)) for key in SETTING_KEYS]


def config_profiles() -> dict[str, dict[str, object]]:
    """Returns named model profiles from the user config only (never from .run-block.json)."""
    raw = user_config().get("profiles")
    if not isinstance(raw, dict):
        return {}
    return {
        str(name): {k: v for k, v in entry.items() if k in PROFILE_FIELDS}
        for name, entry in raw.items()
        if isinstance(entry, dict)
    }


def _role_field(role: str, field: str) -> tuple[object, str | None]:
    for source, data in _config_layers("roles"):
        roles = data.get("roles")
        entry = roles.get(role) if isinstance(roles, dict) else None
        if isinstance(entry, dict) and entry.get(field) not in (None, ""):
            return entry[field], source
    return None, None


def config_roles() -> dict[str, dict[str, tuple[object, str]]]:
    out: dict[str, dict[str, tuple[object, str]]] = {}
    for role in ROLE_NAMES:
        fields: dict[str, tuple[object, str]] = {}
        for field in ROLE_FIELDS:
            val, src = _role_field(role, field)
            if src is not None:
                fields[field] = (val, src)
        if fields:
            out[role] = fields
    return out


def _role_env_suffix(role: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", role.upper())


def _profile_selector(role: str | None, override: str | None) -> tuple[str, str] | None:
    if override is not None and override.strip():
        return override.strip(), "cli"
    if role:
        raw = os.environ.get(f"RUN_BLOCK_MODEL_{_role_env_suffix(role)}", "").strip()
        if raw:
            return raw, "env"
    model, model_src = get_setting("model")
    if model and model_src == "env":
        return model, "env"
    if role:
        val, src = _role_field(role, "profile")
        if isinstance(val, str) and val.strip() and src is not None:
            return val.strip(), src
    if model:
        return model, model_src
    for source, data in _config_layers("default_profile"):
        val = data.get("default_profile")
        if isinstance(val, str) and val.strip():
            return val.strip(), source
    return None


def resolve_profile(role: str | None = None, override: str | None = None) -> dict[str, object] | None:
    """Resolves the active model profile: CLI > RUN_BLOCK_MODEL_<ROLE> > RUN_BLOCK_MODEL >
    roles.<role>.profile > model > default_profile. Returns None when nothing is configured and
    raises ValueError for an unknown profile name."""
    role_n = (role or "").strip().lower() or None
    selected = _profile_selector(role_n, override)
    if selected is None:
        return None
    name, source = selected
    profiles = config_profiles()
    if name in profiles:
        fields = dict(profiles[name])
    else:
        provider, sep, model_id = name.partition(":")
        if not sep or provider not in PROVIDER_API_KEY_ENV or not model_id.strip():
            raise ValueError(
                f"unknown model profile {name!r} (define profiles.{name} in {config_file_path()} "
                f"or use <provider>:<model> with provider in {', '.join(PROVIDER_API_KEY_ENV)})"
            )
        fields = {"provider": provider, "model": model_id.strip()}
    resolved: dict[str, object] = {"name": name, "source": source, **fields}
    cache_val, cache_src = get_setting("cache")
    prof_cache_raw = _config_scalar(fields.get("cache"))
    prof_cache = _norm_cache(prof_cache_raw) if prof_cache_raw is not None else None
    resolved["cache"] = cache_val if cache_src == "env" or prof_cache is None else prof_cache
    role_steps: str | None = None
    if role_n:
        resolved["role"] = role_n
        mode, _ = _role_field(role_n, "mode")
        if mode is not None:
            resolved["mode"] = str(mode)
        raw_steps = _config_scalar(_role_field(role_n, "max_steps")[0])
        role_steps = _norm_nonneg_int(raw_steps) if raw_steps is not None else None
    steps_val, steps_src = get_setting("max_steps")
    resolved["max_steps"] = steps_val if steps_src == "env" or role_steps is None else role_steps
    return resolved


def resolve_api_key(profile: dict[str, object]) -> str | None:
    """Resolves a provider API key in parent memory: api_key_env, api_key_cmd, provider env, RUN_BLOCK_API_KEY."""
    env_name = profile.get("api_key_env")
    if isinstance(env_name, str) and env_name.strip():
        val = os.environ.get(env_name.strip(), "").strip()
        if val:
            return val
    cmd = profile.get("api_key_cmd")
    if isinstance(cmd, str) and cmd.strip():
        try:
            r = subprocess.run(
                shlex.split(cmd),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            raise ValueError(f"api_key_cmd failed: {exc}") from None
        if r.returncode != 0:
            raise ValueError(f"api_key_cmd exited with status {r.returncode}")
        val = r.stdout.strip()
        if val:
            return val
    provider = profile.get("provider")
    provider_env = PROVIDER_API_KEY_ENV.get(provider) if isinstance(provider, str) else None
    for name in (provider_env, GENERIC_API_KEY_ENV):
        if name:
            val = os.environ.get(name, "").strip()
            if val:
                return val
    return None


def provider_secret_env_names() -> frozenset[str]:
    """Provider API key variables always stripped from child step environments."""
    names = set(PROVIDER_API_KEY_ENV_VARS)
    for entry in config_profiles().values():
        env_name = entry.get("api_key_env")
        if isinstance(env_name, str) and env_name.strip():
            names.add(env_name.strip())
    return frozenset(names)


def redact_config_value(key: str, value: object) -> object:
    if value not in (None, "") and _SECRET_CONFIG_KEY_RE.search(key):
        return "<redacted>"
    return value


def _config_key_path(key: str) -> list[str]:
    parts = key.strip().split(".")
    if len(parts) == 1 and (parts[0] in _SETTING_SPECS or parts[0] == "default_profile"):
        return parts
    if (
        len(parts) == 3
        and parts[0] == "profiles"
        and _PROFILE_NAME_RE.fullmatch(parts[1])
        and parts[2] in PROFILE_FIELDS
    ):
        return parts
    if len(parts) == 3 and parts[0] == "roles" and parts[1] in ROLE_NAMES and parts[2] in ROLE_FIELDS:
        return parts
    raise ValueError(
        f"unknown config key: {key} (expected a setting, default_profile, "
        "profiles.<name>.<field>, or roles.<role>.<field>)"
    )


def get_config_value(key: str) -> tuple[object, str]:
    parts = _config_key_path(key)
    if len(parts) == 1 and parts[0] in _SETTING_SPECS:
        return get_setting(parts[0], migrate=False)
    if parts[0] == "default_profile":
        for source, data in _config_layers("default_profile"):
            if data.get("default_profile") not in (None, ""):
                return data["default_profile"], source
        return None, "default"
    if parts[0] == "profiles":
        val = config_profiles().get(parts[1], {}).get(parts[2])
        return (val, "config") if val is not None else (None, "default")
    val, src = _role_field(parts[1], parts[2])
    return val, src or "default"


def _parse_config_value(raw: str) -> object:
    text = raw.strip()
    if text in ("true", "false", "null") or re.fullmatch(r"-?\d+(?:\.\d+)?", text):
        return json.loads(text)
    return raw


def write_user_config(data: dict[str, object]) -> Path:
    path = config_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    tmp = path.with_name(f".{path.name}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(payload)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    _CONFIG_JSON_CACHE.pop(str(path), None)
    return path


def set_config_value(key: str, raw_value: str) -> Path:
    """Sets (or with an empty/null value removes) a key in the user config.json (mode 0600)."""
    parts = _config_key_path(key)
    value = _parse_config_value(raw_value) if raw_value.strip() else None
    if value is not None and len(parts) == 1 and parts[0] in _SETTING_SPECS:
        scalar = _config_scalar(value)
        if scalar is None or _SETTING_SPECS[parts[0]][2](scalar) is None:
            raise ValueError(f"invalid value for {key}: {raw_value!r}")
    data = json.loads(json.dumps(user_config()))
    chain: list[dict[str, object]] = [data]
    for part in parts[:-1]:
        child = chain[-1].get(part)
        if not isinstance(child, dict):
            child = {}
            chain[-1][part] = child
        chain.append(child)
    if value is None:
        chain[-1].pop(parts[-1], None)
        for depth in range(len(parts) - 1, 0, -1):
            if not chain[depth]:
                chain[depth - 1].pop(parts[depth - 1], None)
    else:
        chain[-1][parts[-1]] = value
    return write_user_config(data)


def _script_ext() -> str:
    return ".sh"


def _step_dir(sdir: Path, step: str) -> Path:
    return sdir / step


def _find_step_script(sdir: Path, step: str) -> Path:
    return _step_dir(sdir, step) / "block.sh"


def _orig_backup_path(script_path: Path) -> Path:
    ext = script_path.suffix or ".sh"
    return script_path.with_name(f"block.orig{ext}")


def _orig_file_backup_path(target_path: Path) -> Path:
    return target_path.with_name(f"{target_path.name}.orig")


_STEP_DIR_RE = re.compile(r"\d+(?:_\d+)?")
_STEP_ARTIFACTS = ("block.sh", "fix.py", "out", "error", "aborted", "meta.json")
STEP_OUTCOMES = ("ok", "failed", "syntax-error", "not-run", "aborted", "saved")


def _iter_session_steps(sdir: Path) -> list[Path]:
    if not sdir.is_dir():
        return []
    steps = [
        d
        for d in sdir.iterdir()
        if d.is_dir()
        and _STEP_DIR_RE.fullmatch(d.name)
        and any((d / name).exists() for name in _STEP_ARTIFACTS)
    ]
    return sorted(steps, key=lambda d: _step_sort_key(d.name))


def _iter_session_scripts(sdir: Path) -> list[Path]:
    scripts: list[Path] = []
    for d in _iter_session_steps(sdir):
        p = d / "block.sh"
        if p.is_file():
            scripts.append(p)
    return scripts


def get_session_state(sdir: Path) -> str:
    if is_session_completed(sdir):
        return "done"
    if _iter_session_steps(sdir):
        return "active"
    if (sdir / "0").is_file():
        return "bundle-only"
    return "empty"


def default_base_dir(prog: str | None = None, *, migrate: bool = True) -> Path:
    val, _ = get_setting("base_dir", prog=prog, migrate=migrate)
    return Path(val)


HELP_MAX_COLS = 100
HELP_MAX_LABEL_COL = 48


def _help_section(title: str, rows: tuple, fmt: dict, col: int) -> list[str]:
    labels = [label.format(**fmt) for label, _ in rows]
    width = HELP_MAX_COLS - col
    lines = [title]
    for label, (_, desc) in zip(labels, rows):
        wrapped = textwrap.wrap(desc.format(**fmt), width=width, break_long_words=True, break_on_hyphens=False) or [""]
        head = "  " + label
        head_w = display_width(head)
        if head_w + 2 <= col:
            lines.append((head + " " * (col - head_w) + wrapped[0]).rstrip())
            rest = wrapped[1:]
        else:
            lines.append(head)
            rest = wrapped
        lines.extend(" " * col + w for w in rest)
    return lines


def usage_text() -> str:
    prog = prog_name()
    fmt = {"prog": prog, "base_dir": default_base_dir(prog, migrate=False)}
    sections = (*HELP_COMMAND_SECTIONS, ("Options:", HELP_OPTIONS), ("Environment:", HELP_ENV))
    all_labels = [label.format(**fmt) for _, rows in sections for label, _ in rows]
    col = min(max(display_width(x) for x in all_labels) + 4, HELP_MAX_LABEL_COL)
    out = ["Usage:"] + ["  " + s.format(**fmt) for s in HELP_USAGE]
    for title, rows in sections:
        out += ["", *_help_section(title, rows, fmt, col)]
    return "\n".join(out) + "\n"


def _git_toplevel() -> Path | None:
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
    return None


PROJECT_ROOT_MARKERS = (".context.bundle", ".agents_bundle", "AGENTS.md")


def _git_toplevel_or_cwd() -> Path:
    cwd = Path.cwd().resolve()
    top = _git_toplevel()
    if top is not None:
        if cwd == top or top in cwd.parents:
            cur = cwd
            while True:
                if any((cur / marker).is_file() for marker in PROJECT_ROOT_MARKERS):
                    return cur
                if cur == top or cur.parent == cur:
                    break
                cur = cur.parent
        return top
    return cwd


BUNDLE_HEADER_RE = re.compile(r"^([A-Za-z][A-Za-z0-9-]*(?:\s+[A-Za-z0-9-]+)?):\s*(.*)$")


HIDDEN_SESSION_HEADER_KEYS = frozenset({
    "session",
    "next-block",
    "block",
    "workdir",
    "work-dir",
    "sandbox",
    "date",
})

FULLSCREEN_HIDDEN_HEADER_KEYS = frozenset({
    "bundle-boundary",
    "bundle-name",
    "bundle-protocol",
    "chat-lang",
})

# Optional TIME column between ~TOK and KIND in breakdown table rows.
TABLE_TIME_COL_PATTERN = r"(?:[^\s\[]\S*\s+)?"


def is_bundle_transport_header(key: str) -> bool:
    norm = re.sub(r"\s+", "-", key.strip().lower())
    return norm.startswith("bundle-")


def parse_stdin_preamble(stdin_text: str) -> tuple[list[tuple[str, str]], str]:
    """Splits optional leading 'Key: Value' header lines (separated by a blank line) from body."""
    if not stdin_text:
        return [], ""
    lines = stdin_text.replace("\r\n", "\n").splitlines()
    items: list[tuple[str, str]] = []
    index_by_norm: dict[str, int] = {}
    sep_idx: int | None = None
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            if items:
                sep_idx = idx
            break
        m = BUNDLE_HEADER_RE.match(stripped)
        if not m:
            return [], stdin_text.strip()
        raw_key = re.sub(r"\s+", "-", m.group(1).strip())
        norm_key = raw_key.lower()
        val = m.group(2).strip()
        if norm_key in index_by_norm:
            items[index_by_norm[norm_key]] = (raw_key, val)
        else:
            index_by_norm[norm_key] = len(items)
            items.append((raw_key, val))
    else:
        return items, ""
    if sep_idx is None:
        return [], stdin_text.strip()
    body = "\n".join(lines[sep_idx + 1 :]).strip()
    return items, body


def read_session_meta(session_dir: Path | None) -> dict[str, object]:
    if session_dir is None:
        return {}
    meta_file = session_dir / "meta.json"
    if not meta_file.is_file():
        return {}
    try:
        data = json.loads(meta_file.read_text(encoding="utf-8", errors="replace"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_session_meta(
    session_dir: Path,
    headers: list[tuple[str, str]],
    bundle_plan: dict[str, object] | None = None,
) -> Path | None:
    meta_file = session_dir / "meta.json"
    data: dict[str, object] = {}
    if headers:
        data["headers"] = [[k, v] for k, v in headers]
    if bundle_plan is not None:
        data["bundle_plan"] = bundle_plan
    prev = read_session_meta(session_dir)
    for key in _SESSION_STATE_KEYS:
        if key in prev:
            data[key] = prev[key]
    if not data:
        meta_file.unlink(missing_ok=True)
        return None
    payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    fd = os.open(meta_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(payload)
    return meta_file


def update_session_meta(session_dir: Path, **updates: object) -> Path | None:
    meta_file = session_dir / "meta.json"
    data = read_session_meta(session_dir)
    for k, v in updates.items():
        if v is None:
            data.pop(k, None)
        else:
            data[k] = v
    if not data:
        meta_file.unlink(missing_ok=True)
        return None
    payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    fd = os.open(meta_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(payload)
    return meta_file


_SESSION_STATE_KEYS = (
    "completed",
    "completed_at",
    "completed_note",
    "stats",
    "usage",
    "profile",
)
_STAT_COUNTERS = ("steps", "ok", "failed", "fix", "renumbered", "duration_ms")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _session_stats(meta: dict[str, object]) -> dict[str, object]:
    raw = meta.get("stats")
    return dict(raw) if isinstance(raw, dict) else {}


def stat_int(stats: dict[str, object], key: str) -> int:
    try:
        return int(stats.get(key, 0))
    except (TypeError, ValueError):
        return 0


def is_session_completed(session_dir: Path | None) -> bool:
    return bool(read_session_meta(session_dir).get("completed"))


def set_session_completed(session_dir: Path, note: str | None = None) -> dict[str, object]:
    now = _utc_now_iso()
    stats = _session_stats(read_session_meta(session_dir))
    stats["completed_at"] = now
    update_session_meta(
        session_dir,
        completed=True,
        completed_at=now,
        completed_note=(note or "").strip() or None,
        stats=stats,
    )
    return read_session_meta(session_dir)


def clear_session_completed(session_dir: Path) -> None:
    stats = _session_stats(read_session_meta(session_dir))
    stats.pop("completed_at", None)
    update_session_meta(
        session_dir,
        completed=None,
        completed_at=None,
        completed_note=None,
        stats=stats or None,
    )


def update_session_stats(
    session_dir: Path,
    *,
    ok: bool,
    duration_s: float = 0.0,
    is_fix: bool = False,
    renumbered: bool = False,
) -> None:
    stats = _session_stats(read_session_meta(session_dir))
    now = _utc_now_iso()
    stats.setdefault("started_at", now)
    stats["last_step_at"] = now
    counters = {key: stat_int(stats, key) for key in _STAT_COUNTERS}
    counters["steps"] += 1
    counters["ok" if ok else "failed"] += 1
    if is_fix:
        counters["fix"] += 1
    if renumbered:
        counters["renumbered"] += 1
    counters["duration_ms"] += int(round(max(duration_s, 0.0) * 1000))
    stats.update(counters)
    update_session_meta(session_dir, stats=stats)


def format_duration(seconds: float) -> str:
    secs = max(0.0, float(seconds))
    ms = int(round(secs * 1000.0))
    if ms < 1000:
        return f"{ms}ms"
    if round(secs, 1) < 60.0:
        return f"{secs:.1f}s"
    total_s = int(round(secs))
    mins, rem_s = divmod(total_s, 60)
    hours, rem_m = divmod(mins, 60)
    if hours > 0:
        return f"{hours}h {rem_m}m {rem_s}s"
    return f"{rem_m}m {rem_s}s"


def read_step_meta(step_dir: Path | None) -> dict[str, object]:
    if step_dir is None:
        return {}
    meta_file = step_dir / "meta.json"
    if not meta_file.is_file():
        return {}
    try:
        data = json.loads(meta_file.read_text(encoding="utf-8", errors="replace"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_step_meta(
    step_dir: Path,
    *,
    duration_ms: int,
    exit_code: int,
    operations: list[dict[str, object]] | None = None,
    failed_step: int | None = None,
    renumbered_from: str | None = None,
    outcome: str | None = None,
    reason: str | None = None,
    fix_target: str | None = None,
    reasoning: str | None = None,
    reply_transport: str | None = None,
    protocol_violations: dict[str, object] | None = None,
    prompt_injection_warning: bool = False,
) -> Path:
    if outcome is None:
        outcome = "ok" if exit_code == 0 else "failed"
    if outcome not in STEP_OUTCOMES:
        raise ValueError(f"unknown step outcome: {outcome!r}")
    prev = read_step_meta(step_dir)
    if reasoning is None and isinstance(prev.get("reasoning"), str):
        reasoning = str(prev["reasoning"])
    meta_file = step_dir / "meta.json"
    data: dict[str, object] = {
        "outcome": outcome,
        "duration_ms": max(0, int(duration_ms)),
        "exit_code": int(exit_code),
    }
    if reason:
        data["reason"] = str(reason)
    if fix_target:
        data["fix_target"] = str(fix_target)
    if reasoning and str(reasoning).strip():
        data["reasoning"] = str(reasoning).strip()
    if operations:
        data["operations"] = list(operations)
    if failed_step is not None and exit_code != 0:
        data["failed_step"] = int(failed_step)
    if renumbered_from:
        data["renumbered_from"] = str(renumbered_from)
    if reply_transport:
        data["reply_transport"] = str(reply_transport)
    if protocol_violations:
        data["protocol_violations"] = dict(protocol_violations)
    if prompt_injection_warning:
        data["prompt_injection_warning"] = True
    if isinstance(prev.get("usage"), dict):
        data["usage"] = dict(prev["usage"])
    payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    fd = os.open(meta_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(payload)
    return meta_file


def _parse_meta_header_items(session_dir: Path | None) -> list[tuple[str, str]]:
    meta = read_session_meta(session_dir)
    raw_headers = meta.get("headers")
    items: list[tuple[str, str]] = []
    if isinstance(raw_headers, list):
        for entry in raw_headers:
            if isinstance(entry, (list, tuple)) and len(entry) == 2:
                k = re.sub(r"\s+", "-", str(entry[0]).strip())
                v = str(entry[1]).strip()
                if k:
                    items.append((k, v))
    elif isinstance(raw_headers, dict):
        for k_raw, v_raw in raw_headers.items():
            k = re.sub(r"\s+", "-", str(k_raw).strip())
            v = str(v_raw).strip()
            if k:
                items.append((k, v))
    return items


def parse_bundle_header_items(
    session_dir: Path | None,
    include_transport: bool = True,
) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    index_by_norm: dict[str, int] = {}
    if session_dir is None:
        return items
    bundle_file = session_dir / "0"
    if bundle_file.is_file():
        try:
            with bundle_file.open(encoding="utf-8", errors="replace") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    if stripped.startswith("====="):
                        break
                    m = BUNDLE_HEADER_RE.match(stripped)
                    if not m:
                        break
                    raw_key = re.sub(r"\s+", "-", m.group(1).strip())
                    norm_key = raw_key.lower()
                    val = m.group(2).strip()
                    if norm_key in index_by_norm:
                        items[index_by_norm[norm_key]] = (raw_key, val)
                    else:
                        index_by_norm[norm_key] = len(items)
                        items.append((raw_key, val))
        except OSError:
            pass
    has_bundle = bundle_file.is_file()
    for raw_key, val in _parse_meta_header_items(session_dir):
        norm_key = raw_key.lower()
        if has_bundle and norm_key in HIDDEN_SESSION_HEADER_KEYS:
            continue
        if norm_key in index_by_norm:
            if norm_key not in HIDDEN_SESSION_HEADER_KEYS:
                items[index_by_norm[norm_key]] = (raw_key, val)
        else:
            index_by_norm[norm_key] = len(items)
            items.append((raw_key, val))
    if not include_transport:
        return [(k, v) for k, v in items if not is_bundle_transport_header(k)]
    return items


def parse_bundle_headers(session_dir: Path | None) -> dict[str, str]:
    return {k.lower(): v for k, v in parse_bundle_header_items(session_dir)}


def _resolve_existing_dir(raw: str) -> Path | None:
    val = raw.strip()
    if not val:
        return None
    try:
        p = Path(val).expanduser()
        if p.is_dir():
            return p.resolve()
        for old_ch, new_ch in (("_", "-"), ("-", "_")):
            if old_ch in p.name:
                alt = p.with_name(p.name.replace(old_ch, new_ch))
                if alt.is_dir():
                    return alt.resolve()
        p_str = str(p)
        for old_ch, new_ch in (("_", "-"), ("-", "_")):
            if old_ch in p_str:
                alt_full = Path(p_str.replace(old_ch, new_ch))
                if alt_full.is_dir():
                    return alt_full.resolve()
    except OSError:
        pass
    return None


def _session_bundle_workdir(session_dir: Path | None) -> Path | None:
    headers = parse_bundle_headers(session_dir)
    raw = headers.get("workdir") or headers.get("work-dir") or ""
    return _resolve_existing_dir(raw)


_SANDBOX_OFF_TOKENS = ("", "0", "off", "false", "no", "none", "disable", "disabled")
_SANDBOX_STRICT_TOKENS = ("1", "on", "true", "yes", "auto", "strict", "bwrap", "seatbelt", "sandbox-exec")
_SANDBOX_NONET_TOKENS = ("nonet", "no-net", "offline", "bwrap-nonet", "seatbelt-nonet")
SANDBOX_MODE_TOKENS = tuple(t for t in (*_SANDBOX_OFF_TOKENS, *_SANDBOX_STRICT_TOKENS, *_SANDBOX_NONET_TOKENS) if t)


def normalize_sandbox_mode(raw: str) -> str:
    v = raw.strip().lower()
    if v in _SANDBOX_OFF_TOKENS:
        return "off"
    if v in _SANDBOX_STRICT_TOKENS:
        return "strict"
    if v in _SANDBOX_NONET_TOKENS:
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
        if (session_dir / "0").is_file():
            return "off"
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


def parent_run_block_ref() -> tuple[str, str] | None:
    if not in_run_block():
        return None
    sess = (os.environ.get("RUN_BLOCK_PARENT_SESSION") or "").strip()
    step = (os.environ.get("RUN_BLOCK_PARENT_STEP") or "").strip()
    if not sess or not step:
        return None
    if not re.fullmatch(r"[A-Za-z0-9._-]+", sess):
        return None
    if not re.fullmatch(r"\d+(?:_\d+)?", step):
        return None
    return sess, step


def _parent_step_dir_from_env() -> Path | None:
    ref = parent_run_block_ref()
    if ref is None:
        return None
    sess, step = ref
    base = default_base_dir()
    step_d = base / sess / step
    return step_d if step_d.is_dir() else None


def append_deferred_card(kind: str, **payload: object) -> bool:
    step_d = _parent_step_dir_from_env()
    if step_d is None:
        return False
    deferred_file = step_d / "deferred.json"
    cards: list[dict[str, object]] = []
    if deferred_file.is_file():
        try:
            raw = json.loads(deferred_file.read_text(encoding="utf-8", errors="replace"))
            if isinstance(raw, list):
                cards = [c for c in raw if isinstance(c, dict)]
        except (OSError, ValueError):
            cards = []
    entry: dict[str, object] = {"kind": kind}
    entry.update(payload)
    cards.append(entry)
    text = json.dumps(cards, indent=2, ensure_ascii=False) + "\n"
    fd = os.open(deferred_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    return True


def pop_deferred_cards(step_dir: Path | None) -> list[dict[str, object]]:
    if step_dir is None:
        return []
    deferred_file = step_dir / "deferred.json"
    if not deferred_file.is_file():
        return []
    cards: list[dict[str, object]] = []
    try:
        raw = json.loads(deferred_file.read_text(encoding="utf-8", errors="replace"))
        if isinstance(raw, list):
            cards = [c for c in raw if isinstance(c, dict)]
    except (OSError, ValueError):
        cards = []
    deferred_file.unlink(missing_ok=True)
    return cards


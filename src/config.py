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


def clipboard_mode() -> str:
    val, _ = get_setting("clipboard")
    if val in ("never", "off", "0", "false", "no"):
        return "never"
    if val in ("auto", "always"):
        return "auto"
    return "prompt"


def no_clipboard() -> bool:
    return clipboard_mode() == "never"

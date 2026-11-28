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

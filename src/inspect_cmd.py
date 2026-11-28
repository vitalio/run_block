def _done_badge(sdir: Path) -> str:
    return " [DONE]" if is_session_completed(sdir) else ""


def _parse_iso_utc(ts: object) -> float | None:
    if not isinstance(ts, str) or not ts.strip():
        return None
    raw = ts.strip()
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.fromisoformat(raw).timestamp()
    except ValueError:
        return None


def _session_stats_lines(meta: dict[str, object]) -> list[str]:
    stats = _session_stats(meta)
    total = stat_int(stats, "steps")
    outcomes = [
        f"{count} {label}"
        for key, label in (("ok", "ok"), ("failed", "failed"))
        if (count := stat_int(stats, key)) > 0
    ]
    modifiers = [
        f"{count} {label}"
        for key, label in (("fix", "fix"), ("renumbered", "renumbered"))
        if (count := stat_int(stats, key)) > 0
    ]
    groups = [", ".join(g) for g in (outcomes, modifiers) if g]
    steps_line = f"Steps: {total} ({' · '.join(groups)})" if groups else f"Steps: {total}"

    exec_dur = format_duration(stat_int(stats, "duration_ms") / 1000.0)
    started_at = stats.get("started_at")
    completed_at = meta.get("completed_at") or stats.get("completed_at")
    start_ts = _parse_iso_utc(started_at)
    end_ts = _parse_iso_utc(completed_at)
    if start_ts is not None and end_ts is not None and end_ts > start_ts:
        wall_dur = format_duration(end_ts - start_ts)
        dur_line = f"Duration: {wall_dur} ({exec_dur} exec)"
    else:
        dur_line = f"Duration: {exec_dur}"

    lines = [steps_line, dur_line]
    if started_at:
        lines.append(f"Started: {started_at}")
    if completed_at:
        lines.append(f"Completed: {completed_at}")
    if meta.get("completed_note"):
        lines.append(f"Note: {meta['completed_note']}")
    return lines


def render_end_session_card(sdir: Path, *, headless: bool = False) -> None:
    name = sdir.name
    meta = read_session_meta(sdir)
    hdr = format_session_header_lines(label=name, sdir=sdir)
    lines = [*hdr, "", *_session_stats_lines(meta)]
    if headless:
        body = [
            ln
            for ln in lines
            if ln.strip() and not re.match(r"^Session:\s+", ln)
        ]
        sys.stdout.write(f"[{name}] END SESSION\n" + "".join(f"{ln}\n" for ln in body))
    else:
        sys.stdout.write(format_info_box("END SESSION", lines) + "\n")
    sys.stdout.flush()


def cmd_done(session: str | None = None, note: str | None = None, auto_yes: bool = False) -> int:
    headless = auto_yes or os.environ.get("RUN_BLOCK_HEADLESS") == "1"
    base = ensure_base()
    if session:
        sdir = base / session
        if not sdir.is_dir():
            raise SystemExit(f"{prog_name()}: session {session!r} not found in {base}")
    else:
        parent_ref = parent_run_block_ref()
        if parent_ref is not None and (base / parent_ref[0]).is_dir():
            sdir = base / parent_ref[0]
        else:
            found = _find_latest_session_dir()
            if found is None:
                raise SystemExit(f"{prog_name()}: no sessions found in {base}")
            sdir = found
    name = sdir.name
    if is_session_completed(sdir):
        when = read_session_meta(sdir).get("completed_at") or "unknown time"
        sys.stdout.write(f"{prog_name()}: session {name} is already marked as completed ({when})\n")
        return 0
    set_session_completed(sdir, note=note)
    if in_run_block() and append_deferred_card("end_session", session=name):
        sys.stdout.write(f"{prog_name()}: session {name} marked completed\n")
        sys.stdout.flush()
        return 0
    render_end_session_card(sdir, headless=headless)
    return 0


def _step_sort_key(stem: str) -> tuple[int, int]:
    if "_" in stem:
        b, s = stem.split("_", 1)
        return (int(b) if b.isdigit() else 0, int(s) if s.isdigit() else 0)
    return (int(stem) if stem.isdigit() else 0, 0)


def _meta_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _legacy_end_info(kind: str, rest: str, info: dict[str, object]) -> None:
    rc_m = re.search(r"exit (\d+)", rest)
    if rc_m:
        info["exit_code"] = int(rc_m.group(1))
    if kind == "NOT RUN":
        info["outcome"] = "not-run"
        info["reason"] = rest.lstrip(": ").strip() or None
        return
    if "syntax error" in rest:
        info["outcome"] = "syntax-error"
        return
    info["outcome"] = "failed" if (kind == "FAILED" or rc_m) else "ok"
    dur_m = re.search(r"\((?:exit \d+, )?([^)]+)\)", rest)
    if dur_m and not dur_m.group(1).startswith("exit"):
        info["duration"] = dur_m.group(1)


def _apply_legacy_step_artifacts(
    sdir: Path, stem: str, meta: dict[str, object], info: dict[str, object]
) -> None:
    step_d = _step_dir(sdir, stem)
    if (step_d / "aborted").exists():
        info["outcome"] = "aborted"
        return
    if "exit_code" in meta:
        info["outcome"] = "ok" if info["exit_code"] == 0 else "failed"
        return
    label = f"{sdir.name}/{stem}"
    pat = re.compile(rf"^\[{re.escape(label)}\]\s+(END|SUCCESS|FAILED|NOT RUN)([^\n]*)", re.MULTILINE)
    for candidate in (step_d / "out", step_d / "error"):
        if candidate.is_file():
            matches = pat.findall(candidate.read_text(encoding="utf-8", errors="replace"))
            if matches:
                kind, rest = matches[-1]
                _legacy_end_info(kind, rest.split("—")[0], info)
            return


def _step_outcome(sdir: Path, stem: str) -> dict[str, object]:
    meta = read_step_meta(_step_dir(sdir, stem))
    recorded = meta.get("outcome")
    info: dict[str, object] = {
        "outcome": recorded if recorded in STEP_OUTCOMES else "saved",
        "exit_code": _meta_int(meta.get("exit_code")),
        "duration_ms": _meta_int(meta.get("duration_ms")),
        "duration": None,
        "reason": meta.get("reason") or None,
        "fix_target": meta.get("fix_target") or None,
    }
    if recorded not in STEP_OUTCOMES:
        _apply_legacy_step_artifacts(sdir, stem, meta, info)
    duration_ms = info["duration_ms"]
    if info["duration"] is None and isinstance(duration_ms, int):
        info["duration"] = format_duration(duration_ms / 1000.0)
    return info


def _step_status(sdir: Path, stem: str) -> str:
    info = _step_outcome(sdir, stem)
    outcome, rc, dur = info["outcome"], info["exit_code"], info["duration"]
    dur_s = f" ({dur})" if dur else ""
    if outcome == "ok":
        return f"ok{dur_s}"
    if outcome == "failed":
        return f"exit {rc}{dur_s}" if rc is not None else f"failed{dur_s}"
    if outcome == "syntax-error":
        return f"syntax-error (exit {rc})" if rc is not None else "syntax-error"
    return str(outcome)


def _find_latest_step(session: str | None = None) -> tuple[str, str]:
    base = ensure_base()
    if session:
        sdirs = [base / session] if (base / session).is_dir() else []
    else:
        sdirs = sorted(
            [p for p in base.iterdir() if p.is_dir()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    for sdir in sdirs:
        scripts = [p.parent.name for p in _iter_session_scripts(sdir)]
        if scripts:
            return sdir.name, scripts[-1]
    raise SystemExit(f"{prog_name()}: no saved blocks found in {base}")


def _session_open_hint(sdir: Path) -> str:
    if get_session_state(sdir) in ("active", "bundle-only"):
        return f"next: {sdir.name}/{next_free_step(sdir, min_step=1)}"
    return ""


def _session_tail(sdir: Path) -> str:
    hint = _session_open_hint(sdir)
    return f"  {hint}" if hint else _done_badge(sdir)


def _clip_list_desc(desc: str, limit: int = 56) -> str:
    return desc if len(desc) <= limit else desc[: limit - 3] + "..."


def _bundle_row_desc(sdir: Path) -> str:
    headers = {k.lower(): v for k, v in _parse_meta_header_items(sdir)}
    ctx = [f"{label}: {headers[key]}" for key, label in (("task", "Task"), ("role", "Role")) if headers.get(key)]
    joined = "; ".join(ctx)
    return "Session context bundle (0)" + (f"; {joined}" if joined else "")


def _step_row_desc(sdir: Path, stem: str) -> str:
    step_d = _step_dir(sdir, stem)
    script = step_d / "block.sh"
    if script.is_file():
        sh_text = script.read_text(encoding="utf-8", errors="replace")
        summary = summarize_script_actions(sh_text, work_dir=get_work_dir(sdir))
        rows = summary.get("rows") or []
        return _clip_list_desc("; ".join(f"{k}: {v}" for k, v in rows[:2]) if rows else "")
    info = _step_outcome(sdir, stem)
    parts = []
    if info["reason"]:
        parts.append(f"Reason: {info['reason']}")
    if info["fix_target"]:
        parts.append(f"--fix {info['fix_target']}")
    return _clip_list_desc("; ".join(parts))


def _fmt_utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _session_context_text(sdir: Path) -> str:
    headers = parse_bundle_headers(sdir)
    pairs = (("workdir", "Workdir"), ("role", "Role"), ("task", "Task"))
    return "  ".join(f"{label}: {headers[key]}" for key, label in pairs if headers.get(key))


def _session_matches(sdir: Path, query: str) -> bool:
    needle = query.lower()
    values = [sdir.name] + [v for _k, v in parse_bundle_header_items(sdir, include_transport=False)]
    return any(needle in v.lower() for v in values)


def _write_block_rows(sdir: Path, limit: int | None = None) -> None:
    session = sdir.name
    if (sdir / "0").is_file():
        ref0 = f"{session}/0"
        sys.stdout.write(f"  {ref0:<10}  {'bundle':<24}  {_bundle_row_desc(sdir)}\n")
    steps = _iter_session_steps(sdir)
    for step_d in steps if limit is None else steps[-limit:]:
        stem = step_d.name
        ref = f"{session}/{stem}"
        sys.stdout.write(f"  {ref:<10}  {_step_status(sdir, stem):<24}  {_step_row_desc(sdir, stem)}\n")


def cmd_list(session: str | None = None, query: str | None = None) -> int:
    base = ensure_base()
    _warn_if_state_oversized(base)
    if not session:
        sdirs = sorted([p for p in base.iterdir() if p.is_dir()], key=lambda p: (_session_mtime(p), p.name))
        if not sdirs:
            sys.stdout.write(f"No sessions in {base} (0 B)\n")
            return 0
        if query is not None:
            sdirs = [s for s in sdirs if _session_matches(s, query)]
            if not sdirs:
                sys.stdout.write(f"No sessions matching {query!r} in {base}\n")
                return 0
            sys.stdout.write(f"Sessions in {base} matching {query!r}:\n")
        else:
            sys.stdout.write(f"Sessions in {base}:\n")
        total_bytes = 0
        for sdir in sdirs:
            steps = [d.name for d in _iter_session_steps(sdir)]
            sz = _dir_size_bytes(sdir)
            total_bytes += sz
            if steps:
                last = f"{sdir.name}/{steps[-1]} ({_step_status(sdir, steps[-1])})"
            elif (sdir / "0").is_file():
                last = f"{sdir.name}/0 (bundle)"
            else:
                last = "empty"
            sys.stdout.write(
                f"  {sdir.name:<8}  {len(steps):>3} block(s)  {_human_size(sz):>9}  "
                f"{_fmt_utc(_session_mtime(sdir))}   last: {last}{_session_tail(sdir)}\n"
            )
            ctx = _session_context_text(sdir)
            if ctx:
                sys.stdout.write(f"    {ctx}\n")
        sys.stdout.write(f"Total storage: {_human_size(total_bytes)} ({len(sdirs)} session(s))\n")
        session = sdirs[-1].name
        sys.stdout.write(f"\nRecent blocks in {session}:\n")
    else:
        sdir = base / session
        if not sdir.is_dir():
            raise SystemExit(f"{prog_name()}: session {session!r} not found in {base}")
        size = _human_size(_dir_size_bytes(sdir))
        hint = _session_open_hint(sdir)
        detail = f"{size}, {hint}" if hint else size
        sys.stdout.write(f"Blocks in {session} ({detail}){_done_badge(sdir)}:\n")
    _write_block_rows(base / session, limit=15)
    return 0


def cmd_info(session: str | None = None) -> int:
    base = ensure_base()
    if session is None:
        session = _find_latest_session()
    sdir = base / session
    if not sdir.is_dir():
        raise SystemExit(f"{prog_name()}: session {session!r} not found in {base}")
    meta = read_session_meta(sdir)
    lines = [
        f"Session: {session}",
        f"Path: {sdir}",
        f"State: {get_session_state(sdir)}",
        f"Size: {_human_size(_dir_size_bytes(sdir))}",
        f"Updated: {_fmt_utc(_session_mtime(sdir))}",
    ]
    hint = _session_open_hint(sdir)
    if hint:
        lines.append(f"Next: {hint.removeprefix('next: ')}")
    lines.extend(_session_stats_lines(meta))
    lines.append("Headers:")
    items = parse_bundle_header_items(sdir)
    if items:
        lines.extend(f"  {k}: {v}" for k, v in items)
    else:
        lines.append("  (none)")
    lines.append("Blocks:")
    sys.stdout.write("".join(f"{ln}\n" for ln in lines))
    _write_block_rows(sdir)
    return 0


def _find_latest_session() -> str:
    base = ensure_base()
    sdirs = sorted(
        [p for p in base.iterdir() if p.is_dir()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not sdirs:
        raise SystemExit(f"{prog_name()}: no sessions found in {base}")
    return sdirs[0].name


def _show_bundle_part(ref: str | None, part: int) -> int:
    prog = prog_name()
    if ref is None:
        session, step = _find_latest_session(), "0"
    elif "/" in ref:
        session, step = parse_ref(ref, allow_fix_step=True)
    else:
        session, step = parse_ref(f"{ref}/0", allow_fix_step=True)
    if step != "0":
        raise SystemExit(f"{prog}: --part applies only to the <session>/0 bundle (got {session}/{step})")
    sdir = ensure_base() / session
    bundle_path = sdir / "0"
    if not bundle_path.is_file():
        raise SystemExit(f"{prog}: bundle {session}/0 not found ({bundle_path})")
    plan = load_session_bundle_plan(sdir, bundle_path)
    if plan is None:
        raise SystemExit(f"{prog}: no bundle data found for session {session!r}")
    text = bundle_path.read_text(encoding="utf-8", errors="replace")
    try:
        entry, chunk = extract_bundle_part(plan, text, part)
    except ValueError as exc:
        raise SystemExit(f"{prog}: {session}/0: {exc}")
    sys.stderr.write(format_part_header(f"{session}/0", entry, int(plan.get("part_count") or 0)))
    sys.stdout.write(chunk)
    return 0


def _read_step_artifact(path: Path, label: str, what: str) -> str:
    if not path.is_file():
        raise SystemExit(f"{prog_name()}: {what} of {label} not found ({path})")
    return path.read_text(encoding="utf-8", errors="replace")


def cmd_show(ref: str | None = None, part: int | None = None, only: str | None = None) -> int:
    if part is not None:
        return _show_bundle_part(ref, part)
    if ref and "/" not in ref:
        if only is None:
            return cmd_info(ref)
        session, step = _find_latest_step(ref)
    elif ref:
        session, step = parse_ref(ref, allow_fix_step=True)
    else:
        session, step = _find_latest_step()
    sdir = ensure_base() / session
    if step == "0":
        if only is not None:
            raise SystemExit(f"{prog_name()}: --{only} applies only to blocks, not to {session}/0")
        bundle_path = sdir / "0"
        if bundle_path.is_file():
            orig_bundle = _orig_file_backup_path(bundle_path)
            b_suffix = f" (edited) (original: {orig_bundle})" if orig_bundle.is_file() else ""
            sys.stdout.write(f"=== [{session}/0] Bundle: {bundle_path}{b_suffix} ===\n")
            sys.stdout.write(bundle_path.read_text(encoding="utf-8", errors="replace"))
            return 0
        raise SystemExit(f"{prog_name()}: bundle {session}/0 not found ({bundle_path})")
    step_dir = _step_dir(sdir, step)
    script_path = _find_step_script(sdir, step)
    out_path = step_dir / "out"
    err_path = step_dir / "error"
    if not script_path.is_file():
        raise SystemExit(f"{prog_name()}: block {session}/{step} not found ({script_path})")
    if only == "script":
        sys.stdout.write(_read_step_artifact(script_path, f"{session}/{step}", "script"))
        return 0
    if only == "out":
        sys.stdout.write(_read_step_artifact(out_path, f"{session}/{step}", "output"))
        return 0
    orig_path = _orig_backup_path(script_path)
    status_str = _step_status(sdir, step)
    script_edited = f" (edited) (original: {orig_path})" if orig_path.is_file() else ""
    sys.stdout.write(f"=== [{session}/{step}] Script: {script_path} ({status_str}){script_edited} ===\n")
    sys.stdout.write(script_path.read_text(encoding="utf-8", errors="replace"))
    if out_path.is_file():
        out_orig = _orig_file_backup_path(out_path)
        out_edited = f" (edited) (original: {out_orig})" if out_orig.is_file() else ""
        sys.stdout.write(f"\n=== [{session}/{step}] Output: {out_path}{out_edited} ===\n")
        sys.stdout.write(out_path.read_text(encoding="utf-8", errors="replace"))
    if err_path.is_file():
        sys.stdout.write(f"\n=== [{session}/{step}] Error: {err_path} ===\n")
        sys.stdout.write(err_path.read_text(encoding="utf-8", errors="replace"))
    return 0


def _find_latest_session_dir() -> Path | None:
    base = ensure_base()
    sdirs = sorted(
        [p for p in base.iterdir() if p.is_dir()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return sdirs[0] if sdirs else None


def cmd_sandbox(argv: list[str]) -> int:
    prog = prog_name()
    mode_arg: str | None = None
    session_arg: str | None = None
    for a in argv:
        if re.fullmatch(r"s\d+", a) and session_arg is None and mode_arg is not None:
            session_arg = a
        elif mode_arg is None and a.lower() in SANDBOX_MODE_TOKENS:
            mode_arg = normalize_sandbox_mode(a)
        elif session_arg is None and re.fullmatch(r"[A-Za-z0-9._-]+", a) and (ensure_base() / a).is_dir():
            session_arg = a
        elif mode_arg is None:
            mode_arg = normalize_sandbox_mode(a)
        else:
            raise SystemExit(f"{prog}: usage: {prog} --sandbox [off|strict|nonet] [session]")

    base = ensure_base()
    if session_arg:
        sdir: Path | None = base / session_arg
    else:
        parent_ref = parent_run_block_ref()
        if parent_ref is not None and (base / parent_ref[0]).is_dir():
            sdir = base / parent_ref[0]
        else:
            sdir = _find_latest_session_dir()
    backend = detect_sandbox_backend()
    if mode_arg is None:
        cur_mode = get_sandbox_mode(sdir)
        sess_lbl = sdir.name if sdir is not None else "(no active session)"
        sys.stdout.write(
            f"Session: {sess_lbl}\n"
            f"Sandbox: {format_sandbox_header(cur_mode)}\n"
            f"Backend: {backend}\n"
        )
        return 0
    if in_run_block():
        sys.stderr.write(f"{prog}: cannot modify session sandbox settings from inside a running block\n")
        return 2
    if sdir is None:
        sdir = start_session(session_arg, sandbox_mode=mode_arg)
    else:
        sdir.mkdir(mode=0o700, parents=True, exist_ok=True)
        set_session_bundle_header(sdir, "Sandbox", format_sandbox_header(mode_arg))
    sys.stdout.write(
        f"Updated {sdir.name}/0 -> Sandbox: {format_sandbox_header(mode_arg)} (backend: {backend})\n"
    )
    return 0


def _dir_size_bytes(path: Path) -> int:
    total = 0
    try:
        for p in path.rglob("*"):
            if p.is_file():
                try:
                    total += p.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def _session_mtime(sdir: Path) -> float:
    latest = 0.0
    try:
        latest = sdir.stat().st_mtime
        for p in sdir.iterdir():
            try:
                latest = max(latest, p.stat().st_mtime)
            except OSError:
                pass
    except OSError:
        pass
    return latest


_STATE_WARNED_DIRS: set[str] = set()


def _warn_if_state_oversized(base: Path) -> None:
    key = str(base)
    if key in _STATE_WARNED_DIRS:
        return
    raw_limit, _ = get_setting("max_state_mb")
    try:
        limit_mb = float(raw_limit)
    except ValueError:
        limit_mb = 100.0
    if limit_mb <= 0:
        return
    total_bytes = _dir_size_bytes(base)
    if total_bytes > limit_mb * 1024 * 1024:
        _STATE_WARNED_DIRS.add(key)
        prog = prog_name()
        sys.stderr.write(
            f"{prog}: warning: state directory {base} uses {_human_size(total_bytes)} "
            f"(exceeds {limit_mb:g} MB limit; run '{prog} --clean' to prune old sessions)\n"
        )
        sys.stderr.flush()


def _parse_nonneg_float(raw: str, flag_name: str) -> float:
    prog = prog_name()
    try:
        val = float(raw)
    except ValueError:
        raise SystemExit(f"{prog}: invalid {flag_name} value: {raw!r}")
    if math.isnan(val) or math.isinf(val) or val < 0:
        raise SystemExit(f"{prog}: {flag_name} must be >= 0")
    return val


def cmd_clean(argv: list[str]) -> int:
    prog = prog_name()
    usage_msg = (
        f"{prog}: usage: {prog} --clean [--keep N | --older-than DAYS | --max-size MB | --all] [--yes] [session...]"
    )
    keep: int | None = None
    older_than_days: float | None = None
    max_size_mb: float | None = None
    clean_all = False
    yes = False
    target_names: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--all":
            clean_all = True
            i += 1
        elif a in ("-y", "--yes", "--force"):
            yes = True
            i += 1
        elif a == "--keep":
            if i + 1 >= len(argv):
                raise SystemExit(f"{prog}: --keep requires a non-negative integer")
            try:
                keep = int(argv[i + 1])
            except ValueError:
                raise SystemExit(f"{prog}: invalid --keep value: {argv[i + 1]!r}")
            if keep < 0:
                raise SystemExit(f"{prog}: --keep must be >= 0")
            i += 2
        elif a.startswith("--keep="):
            val_s = a.split("=", 1)[1]
            try:
                keep = int(val_s)
            except ValueError:
                raise SystemExit(f"{prog}: invalid --keep value: {val_s!r}")
            if keep < 0:
                raise SystemExit(f"{prog}: --keep must be >= 0")
            i += 1
        elif a == "--older-than":
            if i + 1 >= len(argv):
                raise SystemExit(f"{prog}: --older-than requires a non-negative number of days")
            older_than_days = _parse_nonneg_float(argv[i + 1], "--older-than")
            i += 2
        elif a.startswith("--older-than="):
            older_than_days = _parse_nonneg_float(a.split("=", 1)[1], "--older-than")
            i += 1
        elif a == "--max-size":
            if i + 1 >= len(argv):
                raise SystemExit(f"{prog}: --max-size requires a non-negative size in MB")
            max_size_mb = _parse_nonneg_float(argv[i + 1], "--max-size")
            i += 2
        elif a.startswith("--max-size="):
            max_size_mb = _parse_nonneg_float(a.split("=", 1)[1], "--max-size")
            i += 1
        elif a.startswith("-"):
            raise SystemExit(usage_msg)
        else:
            if not re.fullmatch(r"[A-Za-z0-9._-]+", a):
                raise SystemExit(f"{prog}: invalid session name: {a!r}")
            if a not in target_names:
                target_names.append(a)
            i += 1

    has_policy_flag = clean_all or keep is not None or older_than_days is not None or max_size_mb is not None
    if target_names and has_policy_flag:
        raise SystemExit(f"{prog}: cannot combine explicit session names with --keep/--older-than/--max-size/--all")

    base = ensure_base()
    sdirs = sorted(
        [p for p in base.iterdir() if p.is_dir()],
        key=lambda p: (_session_mtime(p), p.name),
    )
    sizes_by_dir: dict[Path, int] = {d: _dir_size_bytes(d) for d in sdirs}
    total_before = sum(sizes_by_dir.values())

    if target_names:
        by_name = {d.name: d for d in sdirs}
        to_remove: list[Path] = []
        for name in target_names:
            if name not in by_name:
                raise SystemExit(f"{prog}: session {name!r} not found in {base}")
            to_remove.append(by_name[name])
    elif clean_all:
        to_remove = list(sdirs)
    else:
        if not has_policy_flag:
            keep = 5
        remove_set: set[Path] = set()
        if older_than_days is not None:
            cutoff = time.time() - older_than_days * 86400.0
            for d in sdirs:
                if _session_mtime(d) < cutoff:
                    remove_set.add(d)
        if keep is not None:
            remaining = [d for d in sdirs if d not in remove_set]
            if keep == 0:
                remove_set.update(remaining)
            elif len(remaining) > keep:
                remove_set.update(remaining[: len(remaining) - keep])
        if max_size_mb is not None:
            max_bytes = int(max_size_mb * 1024 * 1024)
            remaining = [d for d in sdirs if d not in remove_set]
            rem_total = sum(sizes_by_dir[d] for d in remaining)
            for d in remaining:
                if rem_total <= max_bytes:
                    break
                remove_set.add(d)
                rem_total -= sizes_by_dir[d]
        to_remove = [d for d in sdirs if d in remove_set]

    if not to_remove:
        sys.stdout.write(
            f"Nothing to clean in {base} ({len(sdirs)} session(s), {_human_size(total_before)} total).\n"
        )
        return 0

    freed_bytes = sum(sizes_by_dir[d] for d in to_remove)
    remaining_bytes = max(0, total_before - freed_bytes)
    details = ", ".join(f"{d.name} ({_human_size(sizes_by_dir[d])})" for d in to_remove)
    if not yes and sys.stdin.isatty() and sys.stdout.isatty() and not no_clipboard():
        ok = prompt_yes_no_box(
            "CLEAN SESSIONS",
            [
                f"Directory: {base}",
                f"Total size: {_human_size(total_before)}",
                f"Remove: {len(to_remove)} session(s) ({details})",
                f"Free: {_human_size(freed_bytes)} ({freed_bytes:,} bytes)",
            ],
            f"Delete {len(to_remove)} session(s)?",
            default_yes=False,
            yes_status=f"✓ Removing {len(to_remove)} session(s).",
            no_status="✗ Clean canceled.",
        )
        if not ok:
            return 2

    for d in to_remove:
        shutil.rmtree(d, ignore_errors=True)
    kept = len(sdirs) - len(to_remove)
    sys.stdout.write(
        f"Cleaned {len(to_remove)} session(s) ({details}; {_human_size(freed_bytes)} / {freed_bytes:,} bytes freed) "
        f"from {base}; {kept} kept ({_human_size(remaining_bytes)} remaining).\n"
    )
    return 0

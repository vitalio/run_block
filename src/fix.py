_CMP_OP_SYMBOLS: dict[type[ast.cmpop], str] = {
    ast.Eq: "==",
    ast.NotEq: "!=",
    ast.Lt: "<",
    ast.LtE: "<=",
    ast.Gt: ">",
    ast.GtE: ">=",
    ast.Is: "is",
    ast.IsNot: "is not",
    ast.In: "in",
    ast.NotIn: "not in",
}


def _short_repr(val: object, limit: int = 80) -> str:
    r = repr(val)
    if len(r) > limit:
        return r[: limit - 3] + "..."
    return r


def _is_text_expr(node: ast.AST) -> bool:
    return isinstance(node, ast.Name) and node.id == "text"


def _fix_anchor_values(fix_code: str, ns: dict[str, object]) -> list[str]:
    """Evaluate anchor expressions in text.count/replace/find/index, `old in text`, and re.sub/subn/search/findall."""
    try:
        tree = ast.parse(fix_code)
    except SyntaxError:
        return []
    found: list[str] = []

    def _eval_and_add(arg_node: ast.expr) -> None:
        try:
            expr = ast.Expression(body=arg_node)
            ast.fix_missing_locations(expr)
            val = eval(compile(expr, "<fix_anchor>", "eval"), ns)
        except Exception:
            return
        if isinstance(val, str) and val and val not in found:
            found.append(val)

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
        ):
            obj_id = node.func.value.id
            attr = node.func.attr
            if obj_id == "text" and attr in ("count", "replace", "find", "index") and node.args:
                _eval_and_add(node.args[0])
            elif obj_id == "re" and attr in ("sub", "subn") and len(node.args) >= 3 and _is_text_expr(node.args[2]):
                _eval_and_add(node.args[0])
            elif obj_id == "re" and attr in ("search", "findall", "match") and len(node.args) >= 2 and _is_text_expr(node.args[1]):
                _eval_and_add(node.args[0])
        elif isinstance(node, ast.Compare):
            left = node.left
            for op, comp in zip(node.ops, node.comparators):
                if isinstance(op, (ast.In, ast.NotIn)) and _is_text_expr(comp):
                    _eval_and_add(left)
                left = comp
    return found


def _closest_anchor(old: str, text: str) -> tuple[float, int, float, str] | None:
    """Return (score, 1-based line, runner-up score, window) of the best line window."""
    old_lines = old.strip("\n").splitlines() or [old]
    lines = text.splitlines()
    size = len(old_lines)
    if not lines or len(lines) > 20000:
        return None
    target = "\n".join(old_lines)
    scores = []
    for i in range(max(1, len(lines) - size + 1)):
        window = "\n".join(lines[i : i + size])
        scores.append((difflib.SequenceMatcher(None, target, window).ratio(), i + 1))
    scores.sort(key=lambda s: (-s[0], s[1]))
    best_score, best_line = scores[0]
    runner_up = scores[1][0] if len(scores) > 1 else 0.0
    window = "\n".join(lines[best_line - 1 : best_line - 1 + size])
    return best_score, best_line, runner_up, window


REPAIR_MIN_SCORE = 0.85
REPAIR_MIN_MARGIN = 0.05


def _replace_anchor_literal_in_fix(fix_code: str, old: str, new_old: str) -> str | None:
    """Replace string literal(s) evaluating to `old` in `fix_code` regardless of quote style."""
    try:
        tree = ast.parse(fix_code)
    except SyntaxError:
        return None
    lines_keep = fix_code.splitlines(keepends=True)
    line_starts: list[int] = [0]
    for ln in lines_keep:
        line_starts.append(line_starts[-1] + len(ln))

    def _pos_to_index(lineno: int, col_offset: int) -> int | None:
        if not (1 <= lineno <= len(lines_keep)):
            return None
        raw_line = lines_keep[lineno - 1]
        raw_bytes = raw_line.encode("utf-8")
        if not (0 <= col_offset <= len(raw_bytes)):
            return None
        try:
            char_col = len(raw_bytes[:col_offset].decode("utf-8"))
        except UnicodeDecodeError:
            return None
        return line_starts[lineno - 1] + char_col

    spans: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value == old:
            end_ln = getattr(node, "end_lineno", None)
            end_col = getattr(node, "end_col_offset", None)
            if node.lineno is None or node.col_offset is None or end_ln is None or end_col is None:
                continue
            s_idx = _pos_to_index(node.lineno, node.col_offset)
            e_idx = _pos_to_index(end_ln, end_col)
            if s_idx is not None and e_idx is not None and s_idx < e_idx:
                spans.append((s_idx, e_idx))

    if spans:
        spans = sorted(set(spans))
        for prev_sp, next_sp in zip(spans, spans[1:]):
            if prev_sp[1] > next_sp[0]:
                return None
        patched = fix_code
        replacement = repr(new_old)
        for s_idx, e_idx in reversed(spans):
            patched = patched[:s_idx] + replacement + patched[e_idx:]
        return patched

    if fix_code.count(repr(old)) == 1:
        return fix_code.replace(repr(old), repr(new_old), 1)
    return None


def _propose_anchor_repair(
    fix_code: str,
    text: str,
    ns: dict[str, object],
    label: str,
    sdir: Path,
    *,
    out_path: Path | None = None,
    fix_path: Path | None = None,
) -> tuple[str | None, bool]:
    """Offer to swap a single missing anchor for its unambiguous closest match; return (new_fix_code, prompted)."""
    missing = [v for v in _fix_anchor_values(fix_code, ns) if text.count(v) == 0]
    if len(missing) != 1:
        return None, False
    old = missing[0]
    close = _closest_anchor(old, text)
    if close is None:
        return None, False
    score, line_no, runner_up, window = close
    if score < REPAIR_MIN_SCORE or score - runner_up < REPAIR_MIN_MARGIN:
        return None, False
    new_old = window + ("\n" if old.endswith("\n") else "")
    if new_old == old:
        return None, False
    patched = _replace_anchor_literal_in_fix(fix_code, old, new_old)
    if patched is None or patched == fix_code:
        return None, False
    lines = [
        f"Anchor not found; closest match at line {line_no} (similarity {score:.2f}):",
        f"- {old.strip()}",
        f"+ {window.strip()}",
    ]
    if out_path is not None:
        lines.append(f"Output: {out_path}")
    choice = prompt_yes_no_box(
        "NOT RUN",
        lines,
        "Replace anchor with closest match?",
        default_yes=False,
        script_path=fix_path,
        out_path=out_path,
        label=label,
        sdir=sdir,
    )
    if choice is not True:
        return None, True
    return patched, True


def _anchor_in_referenced_file(old: str, script_text: str, work_dir: Path | None) -> str | None:
    """Return a file path named in the script that contains the anchor text, if any."""
    if work_dir is None:
        return None
    for token in dict.fromkeys(re.findall(r"[\w./-]+\.\w+", script_text)):
        cand = work_dir / token
        try:
            if cand.is_file() and cand.stat().st_size < 2_000_000 and old in cand.read_text(encoding="utf-8"):
                return token
        except (OSError, UnicodeDecodeError):
            continue
    return None


def _fix_anchor_hints(
    fix_code: str, text: str, ns: dict[str, object], next_seq_ref: str, work_dir: Path | None = None
) -> list[str]:
    """Concrete `Hint:` lines for common --fix authoring mistakes."""
    hints: list[str] = []
    for old in _fix_anchor_values(fix_code, ns):
        count = text.count(old)
        if count == 1:
            continue
        if count > 1:
            hints.append(
                f"Hint: anchor {_short_repr(old, 40)} matches {count} times; "
                "extend it with surrounding lines so it is unique"
            )
            continue
        stripped = old.rstrip("\n")
        if stripped != old and text.count(stripped) == 1:
            hints.append("Hint: anchor matches once without its trailing newline; drop the trailing newline from old")
            continue
        repo_file = _anchor_in_referenced_file(old, text, work_dir)
        if repo_file:
            hints.append(
                f"Hint: anchor is not in the target script but exists in {repo_file}; "
                f"--fix patches only the script, so emit a fresh {next_seq_ref} block that edits that file"
            )
            continue
        close = _closest_anchor(old, text)
        if close is not None and close[0] >= 0.5:
            hints.append(
                f"Hint: closest match at line {close[1]} (similarity {close[0]:.2f}): "
                f"{_short_repr(close[3].strip(), 60)}"
            )
        else:
            hints.append(
                f"Hint: anchor {_short_repr(old, 40)} not found in the target script; "
                f"if the text lives elsewhere, emit a fresh {next_seq_ref} block instead of --fix"
            )
    try:
        tree = ast.parse(fix_code)
    except SyntaxError:
        return hints
    for node in tree.body:
        if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)):
            continue
        func = node.value.func
        if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)):
            continue
        name = f"{func.value.id}.{func.attr}"
        if name in ("text.replace", "re.sub", "re.subn"):
            hints.append(f"Hint: line {node.lineno}: result of {name}(...) is discarded; assign it back with text = ...")
    return hints


_SHELL_START_RE = re.compile(
    r"^(?:#!|set\s+-|cd(?:\s|$)|git(?:\s|$)|python3?(?:\s|$)|echo(?:\s|$)|cat(?:\s|$)|grep(?:\s|$)"
    r"|awk(?:\s|$)|sed(?:\s|$)|ls\b|pwd\b|todo(?:_md)?\b|run(?:_block)?\b"
    r"|export\s|mkdir\s|rm\s|cp\s|mv\s|chmod\s|find\s|sh(?:\s|$)|bash(?:\s|$)|pytest\b|make\b)"
)


def _looks_like_shell_script(fix_code: str) -> bool:
    nonblank = [ln.strip() for ln in fix_code.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    first = next((ln.strip() for ln in fix_code.splitlines() if ln.strip()), "")
    if _SHELL_START_RE.match(first) or (nonblank and _SHELL_START_RE.match(nonblank[0])) or "<<'" in fix_code:
        if "text" not in fix_code:
            return True
        if not any(tok in fix_code for tok in ("text.", "text =", "text=", "in text", ", text")):
            return True
    return False


def _fix_syntax_context(fix_code: str) -> list[str]:
    """Code snippet (+-2 lines) and escaping hint for a --fix payload that fails to parse."""
    try:
        ast.parse(fix_code)
    except SyntaxError as exc:
        lineno, msg = exc.lineno, exc.msg or ""
    else:
        return []
    lines = fix_code.splitlines()
    out: list[str] = []
    if lineno is not None and 1 <= lineno <= len(lines):
        out.append(f"Context (line {lineno}):")
        for n in range(max(1, lineno - 2), min(len(lines), lineno + 2) + 1):
            mark = ">" if n == lineno else " "
            out.append(f"{mark} {n:>3} | {lines[n - 1]}")
    if any(k in msg for k in ("unterminated", "continuation", "unicode", "unexpected character", "EOF")):
        out.append(
            "Hint: the RUN_FIX heredoc passes text literally; write newlines as \\n inside Python "
            "string literals and build triple backticks via chr(96) * 3"
        )
    return out


def _format_fix_exception(
    exc: BaseException, fix_code: str, fix_path: Path, ns: dict[str, object]
) -> str:
    lineno: int | None = getattr(exc, "lineno", None)
    tb = exc.__traceback__
    while tb is not None:
        if tb.tb_frame.f_code.co_filename == str(fix_path):
            lineno = tb.tb_lineno
        tb = tb.tb_next

    lines = fix_code.splitlines()
    stmt_node: ast.stmt | None = None
    if lineno is not None:
        try:
            tree = ast.parse(fix_code)
            for node in ast.walk(tree):
                if isinstance(node, ast.stmt) and hasattr(node, "lineno"):
                    end_ln = getattr(node, "end_lineno", node.lineno) or node.lineno
                    if node.lineno <= lineno <= end_ln:
                        if stmt_node is None or node.lineno >= stmt_node.lineno:
                            stmt_node = node
        except Exception:
            stmt_node = None

    stmt_str = ""
    if stmt_node is not None:
        seg = ast.get_source_segment(fix_code, stmt_node)
        if seg:
            stmt_str = " ".join(l.strip() for l in seg.splitlines() if l.strip())
    if not stmt_str and lineno is not None and 1 <= lineno <= len(lines):
        stmt_str = lines[lineno - 1].strip()

    actual_part = ""
    if (
        isinstance(exc, AssertionError)
        and isinstance(stmt_node, ast.Assert)
        and isinstance(stmt_node.test, ast.Compare)
        and len(stmt_node.test.ops) == 1
        and len(stmt_node.test.comparators) == 1
    ):
        op_sym = _CMP_OP_SYMBOLS.get(type(stmt_node.test.ops[0]))
        if op_sym:
            try:
                left_expr = ast.Expression(body=stmt_node.test.left)
                right_expr = ast.Expression(body=stmt_node.test.comparators[0])
                ast.fix_missing_locations(left_expr)
                ast.fix_missing_locations(right_expr)
                left_val = eval(compile(left_expr, "<fix_eval>", "eval"), ns)
                right_val = eval(compile(right_expr, "<fix_eval>", "eval"), ns)
                actual_part = f" (actual: {_short_repr(left_val)} {op_sym} {_short_repr(right_val)})"
            except Exception:
                actual_part = ""

    exc_name = type(exc).__name__
    exc_msg = str(exc).strip()
    if lineno is not None and stmt_str:
        loc_str = f"at line {lineno}: {stmt_str}{actual_part}"
        if exc_msg:
            return f"fix raised {exc_name}: {exc_msg} ({loc_str})"
        return f"fix raised {exc_name} {loc_str}"
    if exc_msg:
        return f"fix raised {exc_name}: {exc_msg}"
    return f"fix raised {exc_name}"


def _find_fix_chain_scripts(sdir: Path, base_step: str) -> list[tuple[str, Path]]:
    chain: list[tuple[str, Path]] = []
    base_script = _find_step_script(sdir, base_step)
    if base_script.is_file():
        chain.append((base_step, base_script))
    if sdir.is_dir():
        fix_items: list[tuple[int, str, Path]] = []
        pat = re.compile(rf"^{re.escape(base_step)}_(\d+)$")
        for d in sdir.iterdir():
            m = pat.match(d.name)
            if m and d.is_dir():
                sub_idx = int(m.group(1))
                step_name = f"{base_step}_{sub_idx}"
                sp = _find_step_script(sdir, step_name)
                if sp.is_file():
                    fix_items.append((sub_idx, step_name, sp))
        for _, step_name, p in sorted(fix_items, key=lambda x: x[0]):
            chain.append((step_name, p))
    return chain


def _consecutive_failed_fixes(sdir: Path, base_step: str) -> int:
    if not sdir.is_dir():
        return 0
    indices: set[int] = set()
    pat = re.compile(rf"^{re.escape(base_step)}_(\d+)$")
    for d in sdir.iterdir():
        m = pat.match(d.name)
        if m and d.is_dir():
            indices.add(int(m.group(1)))
    failures = 0
    for idx in sorted(indices):
        stem = f"{base_step}_{idx}"
        outcome = _step_outcome(sdir, stem)["outcome"]
        if outcome == "aborted":
            continue
        if outcome == "ok":
            failures = 0
        else:
            failures += 1
    return failures


def cmd_fix(
    ref: str,
    fix_code: str,
    auto_yes: bool = False,
    sandbox_override: str | None = None,
    _repair: bool = True,
    *,
    reasoning: str | None = None,
    renumbered_from: str | None = None,
    _allocated_step: str | None = None,
    reply_transport: str | None = None,
    protocol_violations: dict[str, object] | None = None,
) -> int:
    if in_run_block():
        return _reject_nested_step_execution(f"--fix {ref}")
    fix_code, split_err, split_meta = _reassemble_split_payload_with_meta(fix_code)
    merged_violations = _merge_protocol_violation_dicts(protocol_violations, split_meta)
    headless = os.environ.get("RUN_BLOCK_HEADLESS") == "1"
    session, target = parse_ref(ref, allow_fix_step=True)
    target_ref = f"{session}/{target}"
    base_step = target.split("_", 1)[0]
    sdir = ensure_base() / session
    next_seq_ref = f"{session}/{next_free_step(sdir, min_step=int(base_step) + 1)}"
    new_step = _allocated_step or next_fix_step(target)
    label = f"{session}/{new_step}"
    new_step_dir = _step_dir(sdir, new_step)
    fix_path = new_step_dir / "fix.py"
    existing_script = _find_step_script(sdir, new_step)
    out_path = new_step_dir / "out"
    if split_err:
        return not_run_exit(
            label, sdir, new_step, out_path, f"[{label}] NOT RUN: {split_err}", headless=headless, fix_target=target_ref
        )

    chain = _find_fix_chain_scripts(sdir, base_step)
    if not chain:
        missing_script = _find_step_script(sdir, target)
        return not_run_exit(
            label,
            sdir,
            new_step,
            out_path,
            f"[{label}] NOT RUN: target script {missing_script} does not exist",
            headless=headless,
            fix_target=target_ref,
        )

    rc_done = _guard_completed_session(label, sdir, new_step, out_path, headless, fix_target=target_ref, auto_yes=auto_yes)
    if rc_done is not None:
        return rc_done

    aborted_marker = new_step_dir / "aborted"
    overwrite = aborted_marker.exists()
    if overwrite:
        out_path.unlink(missing_ok=True)
        fix_path.unlink(missing_ok=True)
        existing_script.unlink(missing_ok=True)
        (new_step_dir / "meta.json").unlink(missing_ok=True)
        (new_step_dir / "error").unlink(missing_ok=True)
        aborted_marker.unlink(missing_ok=True)
        for orig_p in (
            new_step_dir / "block.orig.sh",
            new_step_dir / "fix.orig.py",
            new_step_dir / "out.orig",
        ):
            orig_p.unlink(missing_ok=True)
    elif existing_script.exists() or fix_path.exists() or out_path.exists():
        if sys.stdout.isatty() and not no_clipboard() and not headless:
            next_fix = next_fix_step(target, sdir=sdir)
            next_label = f"{session}/{next_fix}"
            existing_lines = [f"Next: {next_label}"]
            info_script = existing_script if existing_script.exists() else (fix_path if fix_path.exists() else None)
            if info_script is not None:
                existing_lines.append(f"Script: {info_script}")
            if out_path.exists():
                existing_lines.append(f"Output: {out_path}")

            def _fix_exists_lines() -> list[str]:
                hdr = format_session_header_lines(
                    label=label, sdir=sdir, sandbox_mode=sandbox_override
                )
                return [*hdr, "", *existing_lines]

            if out_path.exists():
                choice = prompt_yes_no_box(
                    "STEP ALREADY EXISTS",
                    _fix_exists_lines(),
                    "Copy out to clipboard?",
                    default_yes=True,
                    no_status=f"✗ Keeping existing {label}.",
                    script_path=info_script,
                    out_path=out_path,
                    renumber_label=next_label,
                    renumber_status=f"✓ Renumbering {label} -> {next_label}.",
                    content_builder=_fix_exists_lines,
                    copy_on_yes=True,
                    label=label,
                    sdir=sdir,
                    sandbox_mode=sandbox_override,
                    allow_overwrite=True,
                )
            else:
                choice = prompt_yes_no_box(
                    "STEP ALREADY EXISTS",
                    _fix_exists_lines(),
                    f"Renumber to {next_label}?",
                    default_yes=False,
                    no_status=f"✗ Keeping existing {label}.",
                    script_path=info_script,
                    renumber_label=next_label,
                    renumber_status=f"✓ Renumbering {label} -> {next_label}.",
                    content_builder=_fix_exists_lines,
                    renumber_only=True,
                    label=label,
                    sdir=sdir,
                    sandbox_mode=sandbox_override,
                    allow_overwrite=True,
                )
            if choice == "renumber":
                renumbered_from = label
                new_step = next_fix
                label = next_label
                new_step_dir = _step_dir(sdir, new_step)
                fix_path = new_step_dir / "fix.py"
                existing_script = _find_step_script(sdir, new_step)
                out_path = new_step_dir / "out"
                aborted_marker = new_step_dir / "aborted"
                overwrite = False
            elif choice == "overwrite":
                out_path.unlink(missing_ok=True)
                fix_path.unlink(missing_ok=True)
                existing_script.unlink(missing_ok=True)
                (new_step_dir / "meta.json").unlink(missing_ok=True)
                (new_step_dir / "error").unlink(missing_ok=True)
                aborted_marker.unlink(missing_ok=True)
                for orig_p in (
                    new_step_dir / "block.orig.sh",
                    new_step_dir / "fix.orig.py",
                    new_step_dir / "out.orig",
                ):
                    orig_p.unlink(missing_ok=True)
                overwrite = True
            elif choice == "copy":
                return 0
            else:
                return 2
        if not overwrite and renumbered_from is None:
            return not_run_exit(
                label,
                sdir,
                new_step,
                out_path,
                f"[{label}] NOT RUN: step already exists — output: {out_path}",
                headless=headless,
                fix_target=target_ref,
            )

    chain = _find_fix_chain_scripts(sdir, base_step)
    max_attempts = int(get_setting("max_fix_attempts")[0])
    prior_failures = _consecutive_failed_fixes(sdir, base_step)
    if prior_failures >= max_attempts:
        return not_run_exit(
            label,
            sdir,
            new_step,
            out_path,
            (
                f"[{label}] NOT RUN: STOP --fix — reached max consecutive failed --fix attempts "
                f"({prior_failures}/{max_attempts}) for {session}/{base_step}; "
                f"emit a fresh {next_seq_ref} block instead"
            ),
            headless=headless,
            fix_target=target_ref,
        )

    reach_limit = (prior_failures + 1) >= max_attempts
    stop_directive = (
        f"[{label}] STOP --fix: reached {prior_failures + 1}/{max_attempts} failed --fix attempts "
        f"for {session}/{base_step}; switch to a fresh {next_seq_ref} block instead."
    )

    def _fail_not_run(reason: str) -> int:
        msg = f"[{label}] NOT RUN: {reason}"
        if reach_limit:
            msg += f"\n{stop_directive}"
        return not_run_exit(label, sdir, new_step, out_path, msg, headless=headless, fix_target=target_ref)

    if not fix_code.strip():
        return _fail_not_run("empty fix on stdin")

    if _looks_like_shell_script(fix_code):
        return _fail_not_run(
            "--fix payload looks like a shell script, not a Python text patch\n"
            f"Hint: run it as a fresh {next_seq_ref} block instead of --fix"
        )

    ast_ok, ast_err = validate_fix_ast(fix_code)
    if not ast_ok:
        reason = f"unsafe construct in --fix ({ast_err})"
        ctx = _fix_syntax_context(fix_code)
        if ctx:
            reason += "\n" + "\n".join(ctx)
        return _fail_not_run(reason)

    direct_script = _find_step_script(sdir, target)
    if direct_script.is_file():
        primary = (target, direct_script)
    else:
        primary = chain[-1]

    candidates: list[tuple[str, Path]] = [primary]
    for cand_step, cand_path in reversed(chain):
        if all(cand_step != c[0] for c in candidates):
            candidates.append((cand_step, cand_path))

    chosen_step: str | None = None
    chosen_script: Path | None = None
    chosen_orig: str = ""
    chosen_new: str = ""
    primary_err: str | None = None
    primary_text = ""
    primary_ns: dict[str, object] = {}

    for idx, (cand_step, cand_script) in enumerate(candidates):
        cand_orig = cand_script.read_text(encoding="utf-8")
        ns: dict[str, object] = {
            "__builtins__": dict(SAFE_FIX_BUILTINS),
            "text": cand_orig,
            "re": re,
        }
        if idx == 0:
            primary_text, primary_ns = cand_orig, ns
        try:
            exec(compile(fix_code, str(fix_path), "exec"), ns)
        except Exception as exc:
            if idx == 0:
                primary_err = _format_fix_exception(exc, fix_code, fix_path, ns)
            continue
        cand_new = ns.get("text")
        if not isinstance(cand_new, str):
            if idx == 0:
                primary_err = "fix did not leave a string in 'text'"
            continue
        if cand_new == cand_orig:
            if idx == 0:
                primary_err = f"fix made no changes to {cand_script}"
            continue
        chosen_step = cand_step
        chosen_script = cand_script
        chosen_orig = cand_orig
        chosen_new = cand_new
        break

    if chosen_step is None or chosen_script is None:
        reason = primary_err or f"fix made no changes to {primary[1]}"
        hints = _fix_anchor_hints(fix_code, primary_text, primary_ns, next_seq_ref, get_work_dir(sdir))
        if hints:
            reason += "\n" + "\n".join(hints)
        if _repair and not auto_yes and not headless and sys.stdout.isatty() and not no_clipboard():
            msg = f"[{label}] NOT RUN: {reason}"
            if reach_limit:
                msg += f"\n{stop_directive}"
            line = msg if msg.endswith("\n") else msg + "\n"
            detail_lines = reason.splitlines() or [reason]
            new_step_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            _persist_step_reasoning(new_step_dir, reasoning)
            write_private(fix_path, fix_code, overwrite=True)
            write_private(out_path, line, overwrite=True)
            write_step_meta(
                new_step_dir,
                duration_ms=0,
                exit_code=2,
                outcome="not-run",
                reason=detail_lines[0],
                fix_target=target_ref,
                reasoning=reasoning,
            )
            repaired, prompted = _propose_anchor_repair(
                fix_code, primary_text, primary_ns, label, sdir, out_path=out_path, fix_path=fix_path
            )
            if repaired is not None:
                shutil.rmtree(new_step_dir, ignore_errors=True)
                return cmd_fix(
                    ref,
                    repaired,
                    auto_yes=auto_yes,
                    sandbox_override=sandbox_override,
                    _repair=False,
                    reasoning=reasoning,
                    renumbered_from=renumbered_from,
                    _allocated_step=new_step,
                    reply_transport=reply_transport,
                    protocol_violations=merged_violations,
                )
            if prompted:
                return 2
        return _fail_not_run(reason)

    protocol_notes, recorded_violations = format_protocol_reminder_lines(
        label,
        reply_transport=reply_transport or "text",
        protocol_violations=merged_violations,
    )
    ext = chosen_script.suffix or _script_ext()
    new_step_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    _persist_step_reasoning(new_step_dir, reasoning)
    script_path = new_step_dir / f"block{ext}"
    write_private(fix_path, fix_code, overwrite=overwrite)
    write_private(script_path, chosen_new, overwrite=overwrite)
    diff = "".join(
        difflib.unified_diff(
            chosen_orig.splitlines(keepends=True),
            chosen_new.splitlines(keepends=True),
            fromfile=f"{chosen_step}/{chosen_script.name}",
            tofile=f"{new_step}/block{ext}",
        )
    )
    header = [f"[{label}] patched {chosen_step}/{chosen_script.name} -> {new_step}/block{ext}:\n", diff]
    return run_script(
        label,
        script_path,
        out_path,
        header_lines=header,
        auto_yes=auto_yes,
        sandbox_override=sandbox_override,
        footer_on_fail=stop_directive if reach_limit else None,
        renumbered_from=renumbered_from,
        reasoning=reasoning,
        protocol_notes=protocol_notes,
        reply_transport=reply_transport,
        protocol_violations=recorded_violations,
    )

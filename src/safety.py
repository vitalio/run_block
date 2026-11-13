# --- Detailed pre-execution block plan and safety scanner ---
RISK_RULES: list[tuple[str, str, re.Pattern[str]]] = [
    (
        "git-destructive",
        "destructive Git operation",
        re.compile(
            r"\bgit\s+(?:reset\s+--hard|clean\s+-[A-Za-z]*f|push\s+[^\n]*(?:--force|-f\b|--delete)|branch\s+-D\b|tag\s+-d\b|checkout\s+--\s+\.|restore\s+\.|rebase\b|filter-branch\b)"
        ),
    ),
    (
        "git-push",
        "push to remote Git repository",
        re.compile(r"\bgit\s+(?:-C\s+\S+\s+)*push\b"),
    ),
    (
        "net-write",
        "network or remote file write",
        re.compile(
            r"(?:\b(?:curl|wget)\b[^\n]*(?:-X\s*(?:POST|PUT|DELETE|PATCH)\b|--data\b|--form\b|\s-d\s|\s-F\s)|\b(?:scp|rsync)\s)"
        ),
    ),
    (
        "fs-destructive",
        "recursive or destructive file deletion/overwrite",
        re.compile(
            r"(?:\brm\s+-[A-Za-z]*(?:r|f)[A-Za-z]*\b|\bshutil\.rmtree\s*\(|\bos\.(?:remove|unlink)\s*\(|\bdd\s+[^\n]*\bof=|\b(?:mkfs|shred|fdisk)\b|>\s*(?:/etc/|~/.ssh/|\$HOME/\.ssh/))"
        ),
    ),
    (
        "privilege-system",
        "privilege escalation or system modification",
        re.compile(
            r"(?:\b(?:sudo|doas|pkexec|chown|systemctl|service|killall|pkill)\b|\bkill\s+-9\b|\bchmod\s+[0-7]*777\b|\b(?:apt|apt-get|yum|dnf|pacman|brew)\s+(?:install|remove|purge)\b|\bpip3?\s+install\b|\bnpm\s+install\s+-g\b)"
        ),
    ),
    (
        "secrets-exposure",
        "shell trace or credential file access",
        re.compile(
            r"(?:\bset\s+-[A-Za-z]*x\b|\bbash\s+-[A-Za-z]*x\b|\.ssh/id_[A-Za-z0-9_]+(?!\.pub)\b|\.netrc\b|\.aws/credentials\b)"
        ),
    ),
    (
        "remote-exec",
        "piping remote content into a shell or eval",
        re.compile(
            r"(?:\b(?:curl|wget)\b[^\n]*\|\s*(?:sudo\s+)?(?:sh|bash|zsh|python3?)\b|\beval\s+)"
        ),
    ),
]


def get_active_risk_rules() -> list[tuple[str, str, re.Pattern[str]]]:
    cfg = parse_config_file()
    raw_dis, _ = get_setting("safety_disable")
    disabled: set[str] = {
        x.strip().lower()
        for x in re.split(r"[,\s]+", raw_dis)
        if x.strip()
    }
    if "external-write" in disabled:
        disabled.update(("git-push", "net-write"))
    custom_map: dict[str, str] = {}
    for k, v in cfg.items():
        if k.startswith("safety_rule."):
            cat = k[len("safety_rule."):].strip().lower()
            if not cat:
                continue
            if v.strip().lower() in ("off", "none", "false", "0", "disable", "disabled"):
                disabled.add(cat)
            elif v.strip():
                custom_map[cat] = v.strip()
    env_rules = os.environ.get("RUN_BLOCK_SAFETY_RULES", "").strip()
    if env_rules:
        for item in env_rules.split(";"):
            part = item.strip()
            if not part:
                continue
            sep = "=" if "=" in part and (":" not in part or part.index("=") < part.index(":")) else (":" if ":" in part else "")
            if not sep:
                continue
            cat_raw, pat_raw = part.split(sep, 1)
            cat = cat_raw.strip().lower()
            pat_str = pat_raw.strip()
            if not cat:
                continue
            if pat_str.lower() in ("off", "none", "false", "0", "disable", "disabled"):
                disabled.add(cat)
                custom_map.pop(cat, None)
            elif pat_str:
                custom_map[cat] = pat_str
                disabled.discard(cat)

    active: list[tuple[str, str, re.Pattern[str]]] = []
    seen_cats: set[str] = set()
    for cat, desc, pat in RISK_RULES:
        if cat in disabled:
            continue
        if cat in custom_map:
            try:
                active.append((cat, desc, re.compile(custom_map[cat])))
                seen_cats.add(cat)
                continue
            except re.error:
                pass
        active.append((cat, desc, pat))
        seen_cats.add(cat)

    for cat, pat_str in custom_map.items():
        if cat in disabled or cat in seen_cats:
            continue
        try:
            active.append((cat, f"custom safety rule ({cat})", re.compile(pat_str)))
            seen_cats.add(cat)
        except re.error:
            pass
    return active

PY_HEREDOC_START_RE = re.compile(r"python3?\s+-[^\n]*<<-?['\"]?([A-Za-z0-9_]+)['\"]?")
SHELL_HEREDOC_START_RE = re.compile(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?")
HEREDOC_REDIRECT_TARGET_RE = re.compile(r">>?\s*([^\s;<>&|]+)")


def _add_unique(items: list[str], val: str, limit: int = 12) -> None:
    clean = val.strip()
    if clean and clean not in items and len(items) < limit:
        items.append(clean)


def _extract_py_path_expr(node: ast.AST, var_map: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name) and node.id in var_map:
        return var_map[node.id]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = _extract_py_path_expr(node.left, var_map)
        right = _extract_py_path_expr(node.right, var_map)
        if right:
            return f"{left}/{right}" if left and not left.startswith("<") else right
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id == "Path" and node.args:
            return _extract_py_path_expr(node.args[0], var_map)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "home":
            return "~"
    return None


def _analyze_python_ast(
    py_code: str,
    writes: list[str],
    reads: list[str],
    execs: list[str],
    py_risks: list[dict[str, object]],
    start_line_offset: int = 0,
) -> None:
    try:
        tree = ast.parse(py_code)
    except Exception:
        return
    var_map: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            p = _extract_py_path_expr(node.value, var_map)
            if p:
                var_map[node.targets[0].id] = p
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        unparsed = ast.unparse(node) if hasattr(ast, "unparse") else ""
        if isinstance(node.func, ast.Attribute):
            attr = node.func.attr
            owner = _extract_py_path_expr(node.func.value, var_map)
            mod_name = node.func.value.id if isinstance(node.func.value, ast.Name) else ""
            if attr in ("write_text", "write_bytes"):
                _add_unique(writes, owner or "file (python)")
            elif attr in ("read_text", "read_bytes") and owner:
                _add_unique(reads, owner)
            elif attr == "parse" and mod_name == "ast":
                _add_unique(execs, "ast.parse")
            elif mod_name in ("shutil", "os") and attr in ("copy", "copy2", "move", "replace") and len(node.args) >= 2:
                dst = _extract_py_path_expr(node.args[-1], var_map)
                _add_unique(writes, dst or f"{mod_name}.{attr}")
            elif (mod_name == "shutil" and attr == "rmtree") or (mod_name == "os" and attr in ("remove", "unlink", "system")) or attr == "unlink":
                target = _extract_py_path_expr(node.args[0], var_map) if node.args else owner
                _add_unique(writes, f"{attr}({target or '...'})")
                if mod_name in ("shutil", "os"):
                    py_risks.append({
                        "line": start_line_offset + getattr(node, "lineno", 1),
                        "category": "fs-destructive",
                        "description": "destructive Python call",
                        "snippet": unparsed or f"{mod_name}.{attr}(...)",
                    })
        elif isinstance(node.func, ast.Name) and node.func.id == "open" and len(node.args) >= 2:
            mode_node = node.args[1]
            if isinstance(mode_node, ast.Constant) and isinstance(mode_node.value, str):
                if any(m in mode_node.value for m in ("w", "a", "x")):
                    target = _extract_py_path_expr(node.args[0], var_map)
                    _add_unique(writes, target or "open(..., 'w')")


def summarize_script_actions(script_text: str, work_dir: Path | None = None) -> dict[str, object]:
    wdir = work_dir if work_dir is not None else get_work_dir()
    lines = script_text.splitlines()
    non_empty = [l for l in lines if l.strip()]
    writes: list[str] = []
    reads: list[str] = []
    git_cmds: list[str] = []
    exec_cmds: list[str] = []
    cd_dirs: list[str] = []
    operations: list[tuple[str, str]] = []
    operation_groups: list[tuple[str, list[tuple[str, str]]]] = []
    cur_group_dir = ""

    def add_op(tag: str, desc: str) -> None:
        operations.append((tag, desc))
        if not operation_groups or operation_groups[-1][0] != cur_group_dir:
            operation_groups.append((cur_group_dir, [(tag, desc)]))
        else:
            operation_groups[-1][1].append((tag, desc))

    py_blocks = 0
    py_eof: str | None = None
    py_buf: list[str] = []
    py_start = 0
    sh_eof: str | None = None
    sh_cmd: str = ""
    sh_lines: int = 0

    for idx, raw in enumerate(lines, start=1):
        s = raw.strip()
        if py_eof is not None:
            if s == py_eof:
                pw: list[str] = []
                pr: list[str] = []
                pe: list[str] = []
                _analyze_python_ast("\n".join(py_buf), pw, pr, pe, [], py_start)
                for x in pw:
                    _add_unique(writes, x)
                for x in pr:
                    _add_unique(reads, x)
                for x in pe:
                    _add_unique(exec_cmds, x)
                parts = []
                if pw:
                    parts.append("writes: " + ", ".join(pw))
                if pr:
                    parts.append("reads: " + ", ".join(pr))
                if pe:
                    parts.append("calls: " + ", ".join(pe))
                desc = f"{len(py_buf)} lines" + (f" — {'; '.join(parts)}" if parts else "")
                add_op(f"python #{py_blocks}", desc)
                py_eof = None
                py_buf = []
            else:
                py_buf.append(raw)
            continue
        if sh_eof is not None:
            if s == sh_eof:
                line_lbl = f"{sh_lines} line{'s' if sh_lines != 1 else ''}"
                m_redir = HEREDOC_REDIRECT_TARGET_RE.search(sh_cmd)
                if m_redir:
                    target_f = m_redir.group(1).strip("'\"")
                    _add_unique(writes, target_f)
                    add_op("write", f"{sh_cmd} ({line_lbl})")
                elif re.match(r"^git\s+", sh_cmd):
                    _add_unique(git_cmds, sh_cmd)
                    add_op("git", f"{sh_cmd} ({line_lbl})")
                else:
                    _add_unique(exec_cmds, sh_cmd)
                    add_op("exec", f"{sh_cmd} ({line_lbl})")
                sh_eof = None
                sh_cmd = ""
                sh_lines = 0
            else:
                sh_lines += 1
            continue
        if not s or s.startswith("#"):
            continue
        m_py = PY_HEREDOC_START_RE.search(s)
        if m_py:
            py_blocks += 1
            py_eof = m_py.group(1)
            py_buf = []
            py_start = idx
            continue
        m_sh = SHELL_HEREDOC_START_RE.search(s)
        if m_sh:
            sh_eof = m_sh.group(1)
            sh_cmd = s
            sh_lines = 0
            continue
        if re.match(r"^(?:echo|printf)\b", s) and ">" not in s:
            continue
        if re.match(r"^set\s+[+-][A-Za-z]", s):
            continue
        m_cd = re.match(r"^cd\s+(.+)$", s)
        if m_cd:
            raw_target = m_cd.group(1).strip().strip('"').strip("'")
            cur_group_dir = raw_target
            try:
                resolved_cd = (wdir / os.path.expanduser(raw_target)).resolve()
                if resolved_cd != wdir.resolve():
                    _add_unique(cd_dirs, m_cd.group(1).strip())
                else:
                    cur_group_dir = ""
            except Exception:
                _add_unique(cd_dirs, m_cd.group(1).strip())
            continue
        if re.match(r"^git\s+", s):
            _add_unique(git_cmds, s)
            add_op("git", s)
            continue
        if re.match(r"^(?:rm|cp|mv|mkdir|chmod|touch)\s+", s):
            _add_unique(writes, s)
            add_op("write", s)
            continue
        if re.match(r"^(?:cat|grep|ls|head|tail|find|which|command\s+-v|wc|stat|file|sed\s+-n)\s+", s):
            _add_unique(reads, s)
            add_op("read", s)
            continue
        add_op("exec", s)
        _add_unique(exec_cmds, s)

    rows: list[tuple[str, str]] = []
    for label, bucket in (
        ("write", writes),
        ("read", reads),
        ("git", git_cmds),
        ("exec", exec_cmds),
    ):
        if bucket:
            rows.append((label, ", ".join(bucket)))
    sh_tag = "pwsh" if _is_powershell() else "bash"
    meta = f"{len(non_empty)} line{'s' if len(non_empty) != 1 else ''}"
    if py_blocks:
        meta += f", {sh_tag} + {py_blocks} python block{'s' if py_blocks != 1 else ''}"
    else:
        meta += f", {sh_tag}"
    return {
        "meta": meta,
        "rows": rows,
        "operations": operations,
        "operation_groups": operation_groups,
        "cd_dirs": cd_dirs,
        "work_dir": str(wdir),
    }


def scan_script_risks(script_text: str) -> list[dict[str, object]]:
    active_rules = get_active_risk_rules()
    active_cats = {cat for cat, _, _ in active_rules}
    findings: list[dict[str, object]] = []
    py_eof_token: str | None = None
    py_buf: list[str] = []
    py_start = 0
    sh_eof_token: str | None = None
    sh_scan_body: bool = False
    cur_cd_dir: str = ""
    for idx, raw_line in enumerate(script_text.splitlines(), start=1):
        stripped = raw_line.strip()
        if py_eof_token is not None:
            if stripped == py_eof_token:
                py_f: list[dict[str, object]] = []
                _analyze_python_ast("\n".join(py_buf), [], [], [], py_f, py_start)
                for pf in py_f:
                    if str(pf.get("category")) in active_cats:
                        if cur_cd_dir:
                            pf = {**pf, "snippet": f"{pf['snippet']}  (in {cur_cd_dir})"}
                        findings.append(pf)
                py_eof_token = None
                py_buf = []
            else:
                py_buf.append(raw_line)
            continue
        if sh_eof_token is not None:
            if stripped == sh_eof_token:
                sh_eof_token = None
                sh_scan_body = False
                continue
            if not sh_scan_body:
                continue

        if not stripped or stripped.startswith("#"):
            continue
        m_cd = re.match(r"^cd\s+(.+)$", stripped)
        if m_cd:
            cur_cd_dir = m_cd.group(1).strip().strip('"').strip("'")
            continue
        m_py = PY_HEREDOC_START_RE.search(stripped)
        if m_py:
            py_eof_token = m_py.group(1)
            py_buf = []
            py_start = idx
            continue
        if sh_eof_token is None:
            m_sh = SHELL_HEREDOC_START_RE.search(stripped)
            if m_sh:
                sh_eof_token = m_sh.group(1)
                sh_scan_body = bool(re.search(r"\b(?:sh|bash|zsh|sudo|eval)\b", stripped))
        for category, desc, pat in active_rules:
            if pat.search(stripped):
                clean_snip = re.sub(r"\s+", " ", stripped).replace("│", "|")
                if cur_cd_dir and "-C " not in clean_snip:
                    clean_snip = f"{clean_snip}  (in {cur_cd_dir})"
                findings.append(
                    {
                        "line": idx,
                        "category": category,
                        "description": desc,
                        "snippet": clean_snip,
                    }
                )
                break
    deduped: list[dict[str, object]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for f in findings:
        pair = (str(f["category"]), str(f["snippet"]))
        if pair not in seen_pairs:
            seen_pairs.add(pair)
            deduped.append(f)
    return deduped

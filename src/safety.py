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
            r"(?:\brm\s+-[A-Za-z]*(?:r|f)[A-Za-z]*\b|\bshutil\.rmtree\s*\(|\bos\.(?:remove|unlink)\s*\(|\bdd\s+[^\n]*\bof=|\b(?:mkfs|shred|fdisk)\b|>>?\s*(?:/etc/|~/?\.(?:ssh|bashrc|zshrc|profile|gitconfig)|\$HOME/\.(?:ssh|bashrc|zshrc|profile|gitconfig)|\.git/(?:hooks|config)\b))"
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
            r"(?:\b(?:curl|wget)\b[^\n]*\|\s*(?:sudo\s+)?(?:sh|bash|zsh|python3?)\b|\beval\s+|\bbase64\s+(?:-d|--decode)\b[^\n]*\|\s*(?:sh|bash|zsh|python3?)\b)"
        ),
    ),
    (
        "unicode-spoof",
        "hidden bidirectional or zero-width Unicode control characters",
        re.compile(r"[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff\U000e0000-\U000e007f]"),
    ),
]


def get_active_risk_rules() -> list[tuple[str, str, re.Pattern[str]]]:
    raw_dis, _ = get_setting("safety_disable")
    disabled: set[str] = {
        x.strip().lower()
        for x in re.split(r"[,\s]+", raw_dis)
        if x.strip()
    }
    if "external-write" in disabled:
        disabled.update(("git-push", "net-write"))
    custom_map: dict[str, str] = {}
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
            elif mod_name == "subprocess" and attr in ("run", "Popen", "call", "check_call", "check_output"):
                _add_unique(execs, f"subprocess.{attr}")
                py_risks.append({
                    "line": start_line_offset + getattr(node, "lineno", 1),
                    "category": "remote-exec",
                    "description": "Python subprocess execution",
                    "snippet": unparsed or f"subprocess.{attr}(...)",
                })
            elif mod_name == "os" and attr in ("popen", "execl", "execle", "execlp", "execv", "execve", "execvp", "spawnl", "spawnv"):
                _add_unique(execs, f"os.{attr}")
                py_risks.append({
                    "line": start_line_offset + getattr(node, "lineno", 1),
                    "category": "remote-exec",
                    "description": "Python process execution",
                    "snippet": unparsed or f"os.{attr}(...)",
                })
            elif attr in ("urlopen", "urlretrieve") or (mod_name == "socket" and attr in ("connect", "create_connection")):
                _add_unique(execs, f"{mod_name or 'net'}.{attr}")
                py_risks.append({
                    "line": start_line_offset + getattr(node, "lineno", 1),
                    "category": "net-write",
                    "description": "Python network call",
                    "snippet": unparsed or f"{attr}(...)",
                })
        elif isinstance(node.func, ast.Name):
            fn_id = node.func.id
            if fn_id == "open" and len(node.args) >= 2:
                mode_node = node.args[1]
                if isinstance(mode_node, ast.Constant) and isinstance(mode_node.value, str):
                    if any(m in mode_node.value for m in ("w", "a", "x")):
                        target = _extract_py_path_expr(node.args[0], var_map)
                        _add_unique(writes, target or "open(..., 'w')")
            elif fn_id in ("eval", "exec", "__import__"):
                _add_unique(execs, fn_id)
                py_risks.append({
                    "line": start_line_offset + getattr(node, "lineno", 1),
                    "category": "remote-exec",
                    "description": f"dynamic Python {fn_id}()",
                    "snippet": unparsed or f"{fn_id}(...)",
                })


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

    def _infer_op_dir(cmd_str: str) -> tuple[str, str]:
        if cur_group_dir:
            return cur_group_dir, cmd_str
        m_git_c = re.match(r"^git\s+-C\s+([^\s]+)\s+(.+)$", cmd_str)
        if m_git_c:
            raw_d = m_git_c.group(1).strip("'\"")
            return raw_d, f"git {m_git_c.group(2)}"
        tokens = re.findall(r"(?:\$HOME|~|\.\.)/[A-Za-z0-9._-]+(?:/[^\s'\";|&]+)*", cmd_str)
        if tokens:
            first_tok = tokens[0]
            parts = first_tok.split("/")
            if len(parts) >= 2 and parts[0] in ("$HOME", "~", ".."):
                ext_dir = f"{parts[0]}/{parts[1]}"
                try:
                    expanded = ext_dir.replace("$HOME", str(Path.home())).replace("~", str(Path.home()))
                    resolved_ext = (wdir / expanded).resolve()
                    if resolved_ext != wdir.resolve():
                        short_cmd = cmd_str.replace(f"{ext_dir}/", "").replace(f'"{ext_dir}"', ".").replace(ext_dir, ".")
                        return ext_dir, short_cmd
                except Exception:
                    short_cmd = cmd_str.replace(f"{ext_dir}/", "")
                    return ext_dir, short_cmd
        return cur_group_dir, cmd_str

    def add_op(tag: str, desc: str) -> None:
        operations.append((tag, desc))
        g_dir, short_desc = _infer_op_dir(desc) if tag in ("read", "write", "git", "exec") else (cur_group_dir, desc)
        if not operation_groups or operation_groups[-1][0] != g_dir:
            operation_groups.append((g_dir, [(tag, short_desc)]))
        else:
            operation_groups[-1][1].append((tag, short_desc))

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
                add_op("python", desc)
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


def check_script_syntax(script_text: str, work_dir: Path | None = None) -> tuple[bool, str | None, int]:
    wdir = work_dir if work_dir is not None else get_work_dir()
    shell_bin, _ = get_setting("shell")
    is_ps = _is_powershell(shell_bin)
    ext = ".ps1" if is_ps else ".sh"
    fd, tmp_name = tempfile.mkstemp(prefix="rb_chk_", suffix=ext)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(script_text)
        if is_ps:
            ps_check = (
                "$err = $null; "
                "[void][System.Management.Automation.Language.Parser]::ParseFile($args[0], [ref]$null, [ref]$err); "
                "if ($err) { foreach ($e in $err) { [Console]::Error.WriteLine($e.ToString()) }; exit 1 }"
            )
            chk_cmd = [shell_bin, "-NoProfile", "-NonInteractive", "-Command", ps_check, str(tmp_path)]
        else:
            chk_cmd = [shell_bin, "-n", str(tmp_path)]
        chk = subprocess.run(
            chk_cmd,
            cwd=wdir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        if chk.returncode != 0:
            return False, (chk.stdout or "syntax check failed").strip(), chk.returncode
        return True, None, 0
    finally:
        tmp_path.unlink(missing_ok=True)


def analyze_script(
    script_text: str,
    work_dir: Path | None = None,
    label: str | None = None,
    check_syntax: bool = True,
) -> dict[str, object]:
    wdir = (work_dir if work_dir is not None else get_work_dir()).resolve()
    summary = summarize_script_actions(script_text, work_dir=wdir)
    findings = scan_script_risks(script_text)
    syntax_ok = True
    syntax_error: str | None = None
    if check_syntax:
        syntax_ok, syntax_error, _ = check_script_syntax(script_text, work_dir=wdir)
    return {
        "label": label or "",
        "syntax_ok": syntax_ok,
        "syntax_error": syntax_error,
        "work_dir": str(wdir),
        "meta": summary.get("meta", ""),
        "rows": [list(r) for r in (summary.get("rows") or [])],
        "operations": [list(op) for op in (summary.get("operations") or [])],
        "operation_groups": [
            [g_dir, [list(op) for op in g_items]]
            for g_dir, g_items in (summary.get("operation_groups") or [])
        ],
        "cd_dirs": list(summary.get("cd_dirs") or []),
        "findings": findings,
        "safe": bool(syntax_ok and len(findings) == 0),
    }


def run_approve_cmd(
    approve_cmd: str,
    label: str,
    script_text: str,
    plan: dict[str, object],
    script_path: Path | None = None,
) -> tuple[str, str]:
    """Runs external approval command. Returns (decision, note) where decision is 'approve', 'prompt', or 'reject'."""
    payload = {
        **plan,
        "label": label,
        "script_path": str(script_path) if script_path is not None else "",
        "script": script_text,
    }
    env = {
        **os.environ,
        "RUN_BLOCK_LABEL": label,
        "RUN_BLOCK_WORKDIR": str(plan.get("work_dir") or ""),
    }
    if script_path is not None:
        env["RUN_BLOCK_SCRIPT"] = str(script_path)
    try:
        proc = subprocess.run(
            approve_cmd,
            shell=True,
            input=json.dumps(payload, ensure_ascii=False) + "\n",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            check=False,
        )
    except Exception as exc:
        return "reject", f"approve command failed: {exc}"
    note = (proc.stdout or "").strip()
    if proc.returncode == 0:
        return "approve", note
    if proc.returncode == 2:
        return "prompt", note
    return "reject", (note or f"rejected by approve command (exit {proc.returncode})")


def cmd_plan(stdin_text: str) -> int:
    plan = analyze_script(stdin_text, check_syntax=True)
    sys.stdout.write(json.dumps(plan, indent=2, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0 if plan.get("syntax_ok") else 1


SAFE_FIX_BUILTINS: dict[str, object] = {
    "AssertionError": AssertionError,
    "Exception": Exception,
    "IndexError": IndexError,
    "KeyError": KeyError,
    "RuntimeError": RuntimeError,
    "TypeError": TypeError,
    "ValueError": ValueError,
    "False": False,
    "None": None,
    "True": True,
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "chr": chr,
    "dict": dict,
    "enumerate": enumerate,
    "filter": filter,
    "float": float,
    "int": int,
    "isinstance": isinstance,
    "len": len,
    "list": list,
    "map": map,
    "max": max,
    "min": min,
    "ord": ord,
    "print": print,
    "range": range,
    "repr": repr,
    "reversed": reversed,
    "round": round,
    "set": set,
    "slice": slice,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "zip": zip,
}

FORBIDDEN_FIX_CALLS: set[str] = {
    "__import__",
    "breakpoint",
    "compile",
    "delattr",
    "dir",
    "eval",
    "exec",
    "exit",
    "getattr",
    "globals",
    "hasattr",
    "input",
    "locals",
    "memoryview",
    "open",
    "quit",
    "setattr",
    "type",
    "vars",
}


def validate_fix_ast(fix_code: str) -> tuple[bool, str | None]:
    """Validates that a --fix snippet only performs safe in-memory text/regex transformations."""
    try:
        tree = ast.parse(fix_code)
    except SyntaxError as exc:
        return False, f"SyntaxError: {exc}"
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            return False, "import statements are not allowed in --fix patches"
        if isinstance(node, (ast.Global, ast.Nonlocal, ast.ClassDef, ast.AsyncFunctionDef)):
            return False, f"{type(node).__name__} is not allowed in --fix patches"
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            return False, f"access to private/dunder attribute {node.attr!r} is not allowed in --fix"
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            return False, f"access to dunder name {node.id!r} is not allowed in --fix"
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_FIX_CALLS:
                return False, f"call to {node.func.id}() is not allowed in --fix"
    return True, None


SECRET_ENV_RE = re.compile(
    r"^(?:.*_(?:API_KEY|SECRET|SECRET_KEY|TOKEN|PASSWORD|PASSWD|PRIVATE_KEY|CREDENTIAL|CREDENTIALS)|"
    r"AWS_(?:ACCESS_KEY_ID|SECRET_ACCESS_KEY|SESSION_TOKEN)|"
    r"GH_TOKEN|GITHUB_TOKEN|GITLAB_TOKEN|OPENAI_API_KEY|ANTHROPIC_API_KEY|GEMINI_API_KEY)$",
    re.IGNORECASE,
)


def scrub_child_env(env: dict[str, str], sandbox_mode: str) -> dict[str, str]:
    norm = normalize_sandbox_mode(sandbox_mode)
    if norm == "off":
        return env
    cleaned = {k: v for k, v in env.items() if not SECRET_ENV_RE.match(k)}
    if norm == "nonet":
        cleaned.pop("SSH_AUTH_SOCK", None)
        cleaned.pop("SSH_AGENT_PID", None)
    return cleaned


def detect_sandbox_backend() -> str:
    if sys.platform.startswith("linux") and shutil.which("bwrap"):
        return "bwrap"
    if sys.platform == "darwin" and Path("/usr/bin/sandbox-exec").is_file():
        return "sandbox-exec"
    return "env-only"


def build_sandbox_exec(
    exec_cmd: list[str],
    work_dir: Path,
    base_dir: Path,
    sandbox_mode: str,
) -> list[str]:
    norm = normalize_sandbox_mode(sandbox_mode)
    if norm == "off":
        return exec_cmd
    if norm not in ("strict", "nonet"):
        return shlex.split(norm) + list(exec_cmd)

    wdir = work_dir.resolve()
    bdir = base_dir.resolve()
    home = Path.home().resolve()
    secret_rel_subpaths = (".ssh", ".aws", ".gnupg", ".kube", ".config/gh", ".config/gcloud")

    if sys.platform.startswith("linux") and shutil.which("bwrap"):
        cmd: list[str] = [
            "bwrap",
            "--ro-bind", "/", "/",
            "--dev", "/dev",
            "--proc", "/proc",
            "--tmpfs", "/tmp",
            "--die-with-parent",
        ]
        for rel in secret_rel_subpaths:
            sp = home / rel
            if sp.is_dir():
                cmd.extend(["--tmpfs", str(sp)])
        if bdir.exists():
            cmd.extend(["--ro-bind", str(bdir), str(bdir)])
        if wdir.exists():
            cmd.extend(["--bind", str(wdir), str(wdir)])
            git_hooks = wdir / ".git" / "hooks"
            if git_hooks.is_dir():
                cmd.extend(["--ro-bind", str(git_hooks), str(git_hooks)])
        if norm == "nonet":
            cmd.append("--unshare-net")
        cmd.extend(["--", *exec_cmd])
        return cmd

    if sys.platform == "darwin" and Path("/usr/bin/sandbox-exec").is_file():
        tmp_real = Path(tempfile.gettempdir()).resolve()
        rules = [
            "(version 1)",
            "(allow default)",
            '(deny file-write* (subpath "/"))',
            f'(allow file-write* (subpath "{wdir}"))',
            f'(allow file-write* (subpath "{tmp_real}"))',
            '(allow file-write* (subpath "/private/tmp"))',
            '(allow file-write* (subpath "/dev"))',
            f'(deny file-write* (subpath "{bdir}"))',
        ]
        git_hooks = wdir / ".git" / "hooks"
        if git_hooks.exists():
            rules.append(f'(deny file-write* (subpath "{git_hooks}"))')
        for rel in secret_rel_subpaths:
            sp = home / rel
            if sp.exists():
                rules.append(f'(deny file-read* (subpath "{sp}"))')
                rules.append(f'(deny file-write* (subpath "{sp}"))')
        if norm == "nonet":
            rules.append('(deny network* (remote ip))')
        profile = " ".join(rules)
        return ["/usr/bin/sandbox-exec", "-p", profile, *exec_cmd]

    return exec_cmd

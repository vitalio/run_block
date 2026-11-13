def agents_markdown(prog: str | None = None) -> str:
    cmd = prog or prog_name()
    tpl_key = "agents_pwsh" if _is_powershell() else "agents_bash"
    tpl = EMBEDDED_TEMPLATES[tpl_key]
    return tpl.format(cmd=cmd, version=VERSION).rstrip()


def rules_dir_path() -> Path:
    env_dir = os.environ.get("RUN_BLOCK_RULES_DIR")
    if env_dir:
        return Path(env_dir).expanduser()
    return config_file_path().parent / "rules"


def _discover_user_rules() -> dict[str, tuple[str, str]]:
    rdir = rules_dir_path()
    if not rdir.is_dir():
        return {}
    out: dict[str, tuple[str, str]] = {}
    try:
        for p in sorted(rdir.glob("*.md")):
            if p.is_file():
                raw = p.read_text(encoding="utf-8", errors="replace").splitlines()
                desc = f"Custom rule ({p.name})"
                body_lines = raw
                if raw and raw[0].startswith("# Description:"):
                    desc = raw[0].split(":", 1)[1].strip()
                    body_lines = raw[1:]
                out[p.stem.lower()] = (desc, "\n".join(body_lines).strip())
    except OSError:
        pass
    return out


def _discover_presets() -> dict[str, tuple[str, list[str]]]:
    presets: dict[str, tuple[str, list[str]]] = {
        k: (desc, list(items)) for k, (desc, items) in EMBEDDED_PRESETS.items()
    }
    cfg = parse_config_file()
    for k, v in cfg.items():
        if k.startswith("rules_preset.") and v.strip():
            pname = k[len("rules_preset."):].strip().lower()
            items = [x.strip() for x in re.split(r"[,\s]+", v.strip()) if x.strip()]
            if pname and items:
                presets[pname] = (f"Custom preset from config ({v.strip()})", items)
    return presets


RULE_VAR_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*):([^{}]*)\}")


def _render_rule_vars(text: str, vars_map: dict[str, str]) -> str:
    return RULE_VAR_RE.sub(lambda m: vars_map.get(m.group(1), m.group(2)), text)


def _detect_vcs_rule(work_dir: Path | None = None) -> str | None:
    wdir = work_dir if work_dir is not None else get_work_dir()
    if (wdir / ".git").exists():
        return "git"
    if (wdir / "CVS").is_dir():
        return "cvs"
    return None


def resolve_rules_selection(
    args: list[str] | None = None,
    work_dir: Path | None = None,
) -> tuple[list[str], dict[str, str], dict[str, tuple[str, str]]]:
    prog = prog_name()
    user_rules = _discover_user_rules()
    all_rules: dict[str, tuple[str, str]] = {**EMBEDDED_RULES, **user_rules}
    presets = _discover_presets()

    tokens: list[str] = []
    excluded: set[str] = set()
    vars_map: dict[str, str] = {}

    for item in args or []:
        s = item.strip()
        if not s:
            continue
        if "=" in s and not s.startswith("-"):
            k, v = s.split("=", 1)
            k_clean = k.strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k_clean):
                raise SystemExit(f"{prog}: invalid rule variable name {k_clean!r} in {s!r}")
            vars_map[k_clean] = v.strip()
        elif s.startswith("-") and len(s) > 1 and not s.startswith("--"):
            excluded.add(s[1:].strip().lower())
        else:
            tokens.append(s.lower())

    if not tokens:
        tokens = ["default"]

    expanded: list[str] = []

    def expand_token(tok: str, stack: set[str]) -> None:
        if tok == "auto-vcs":
            vcs = _detect_vcs_rule(work_dir)
            if vcs and vcs not in expanded:
                expanded.append(vcs)
            return
        if tok == "all":
            for rk in all_rules:
                if rk not in expanded:
                    expanded.append(rk)
            return
        if tok in presets and tok not in user_rules:
            if tok in stack:
                return
            for sub in presets[tok][1]:
                if "=" in sub and not sub.startswith("-"):
                    k, v = sub.split("=", 1)
                    vars_map.setdefault(k.strip(), v.strip())
                elif sub.startswith("-") and len(sub) > 1:
                    excluded.add(sub[1:].strip().lower())
                else:
                    expand_token(sub.lower(), stack | {tok})
            return
        if tok in all_rules:
            if tok not in expanded:
                expanded.append(tok)
            return
        avail = sorted(set(presets.keys()) | set(all_rules.keys())) + ["all"]
        raise SystemExit(
            f"{prog}: unknown rule or preset {tok!r} (available: {', '.join(avail)})"
        )

    for t in tokens:
        expand_token(t, set())

    final_rules = [r for r in expanded if r not in excluded]
    return final_rules, vars_map, all_rules


def rules_markdown(args: list[str] | None = None, work_dir: Path | None = None) -> str:
    final_rules, vars_map, all_rules = resolve_rules_selection(args, work_dir=work_dir)
    blocks: list[str] = []
    for r in final_rules:
        body = all_rules[r][1].strip()
        if body:
            blocks.append(_render_rule_vars(body, vars_map))
    hdr = f"## Agent Engineering Rules ({', '.join(final_rules)})"
    return hdr + "\n\n" + "\n".join(blocks)


def cmd_rules(argv: list[str]) -> int:
    prog = prog_name()
    if any(a in ("--list", "-l") for a in argv):
        if len(argv) > 1:
            raise SystemExit(f"{prog}: usage: {prog} --agents-rules [ITEM ... | -RULE | KEY=VAL | --list]")
        user_rules = _discover_user_rules()
        presets = _discover_presets()
        rdir = rules_dir_path()
        sys.stdout.write("Rule presets (groups of rules):\n")
        for k, (desc, items) in presets.items():
            sys.stdout.write(f"  {k:<18}  {desc}\n")
            sys.stdout.write(f"  {'':<18}    -> {', '.join(items)}\n")
        sys.stdout.write("  all                 Include all built-in and custom atomic rules\n\n")
        sys.stdout.write("Atomic rules (usable individually, in presets, or excluded via -<rule>):\n")
        for k, (desc, _) in EMBEDDED_RULES.items():
            override = " (overridden by user file)" if k in user_rules else ""
            sys.stdout.write(f"  {k:<18}  {desc}{override}\n")
        custom_only = {k: v for k, v in user_rules.items() if k not in EMBEDDED_RULES}
        sys.stdout.write(f"\nCustom rule files ({rdir}):\n")
        if custom_only:
            for k, (desc, _) in custom_only.items():
                sys.stdout.write(f"  {k:<18}  {desc}\n")
        else:
            sys.stdout.write("  (none — add <rule>.md files to this directory to define custom rules)\n")
        return 0
    for a in argv:
        if a.startswith("--"):
            raise SystemExit(f"{prog}: usage: {prog} --agents-rules [ITEM ... | -RULE | KEY=VAL | --list]")
    sys.stdout.write(rules_markdown(argv) + "\n")
    return 0

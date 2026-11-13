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
        for p in sorted(rdir.rglob("*.md")):
            if p.is_file():
                rel = p.relative_to(rdir).with_suffix("").as_posix().lower()
                raw = p.read_text(encoding="utf-8", errors="replace").splitlines()
                desc = f"Custom rule ({p.name})"
                body_lines = raw
                if raw and raw[0].startswith("# Description:"):
                    desc = raw[0].split(":", 1)[1].strip()
                    body_lines = raw[1:]
                out[rel] = (desc, "\n".join(body_lines).strip())
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
        return "vcs/git"
    if (wdir / "CVS").is_dir():
        return "vcs/cvs"
    return None


def _match_rule_key(token: str, all_rules: dict[str, tuple[str, str]]) -> str | None:
    if token in all_rules:
        return token
    matches = [k for k in all_rules if k.rsplit("/", 1)[-1] == token]
    if len(matches) == 1:
        return matches[0]
    return None


def resolve_rules_selection(
    args: list[str] | None = None,
    work_dir: Path | None = None,
    default_target: str = "default",
    prog: str | None = None,
) -> tuple[list[str], dict[str, str], dict[str, tuple[str, str]]]:
    cmd = prog or prog_name()
    user_rules = _discover_user_rules()
    all_rules: dict[str, tuple[str, str]] = {**EMBEDDED_RULES, **user_rules}
    presets = _discover_presets()

    tokens: list[str] = []
    excluded: set[str] = set()
    cli_vars: dict[str, str] = {}
    preset_vars: dict[str, str] = {}

    for item in args or []:
        s = item.strip()
        if not s:
            continue
        if "=" in s and not s.startswith("-"):
            k, v = s.split("=", 1)
            k_clean = k.strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k_clean):
                raise SystemExit(f"{cmd}: invalid rule variable name {k_clean!r} in {s!r}")
            cli_vars[k_clean] = v.strip()
        elif s.startswith("-") and len(s) > 1 and not s.startswith("--"):
            excluded.add(s[1:].strip().lower())
        else:
            tokens.append(s.lower())

    if not tokens:
        tokens = [default_target]

    expanded: list[str] = []

    def expand_token(tok: str, stack: set[str], from_preset: bool = False) -> None:
        if tok == "blocks":
            b_key = "blocks/pwsh" if _is_powershell() else "blocks/bash"
            if b_key not in expanded:
                expanded.append(b_key)
            return
        if tok in ("vcs/auto", "auto-vcs"):
            vcs = _detect_vcs_rule(work_dir)
            if vcs and vcs not in expanded:
                expanded.append(vcs)
            return
        if tok == "all":
            b_key = "blocks/pwsh" if _is_powershell() else "blocks/bash"
            if b_key not in expanded:
                expanded.append(b_key)
            for rk in all_rules:
                if not rk.startswith("blocks/") and rk not in expanded:
                    expanded.append(rk)
            return
        if tok in presets and tok not in user_rules:
            if tok in stack:
                return
            outer_overrides: dict[str, str] = {}
            for sub in presets[tok][1]:
                if "=" in sub and not sub.startswith("-"):
                    k, v = sub.split("=", 1)
                    outer_overrides[k.strip()] = v.strip()
                elif sub.startswith("-") and len(sub) > 1:
                    excluded.add(sub[1:].strip().lower())
                else:
                    expand_token(sub.lower(), stack | {tok}, from_preset=True)
            # Outer preset overrides inner preset variable defaults
            preset_vars.update(outer_overrides)
            return
        rk = _match_rule_key(tok, all_rules)
        if rk is not None:
            if rk not in expanded:
                expanded.append(rk)
            return
        avail = sorted(set(presets.keys()) | set(all_rules.keys()) | {"blocks", "vcs/auto", "all"})
        raise SystemExit(
            f"{cmd}: unknown rule or preset {tok!r} (available: {', '.join(avail)})"
        )

    for t in tokens:
        expand_token(t, set())

    def is_excluded(rk: str) -> bool:
        leaf = rk.rsplit("/", 1)[-1]
        if rk in excluded or leaf in excluded:
            return True
        if rk.startswith("blocks/") and "blocks" in excluded:
            return True
        return False

    final_rules = [r for r in expanded if not is_excluded(r)]
    # Precedence: rule default < inner preset < outer preset < explicit CLI arg
    vars_map: dict[str, str] = {"cmd": cmd, "version": VERSION, **preset_vars, **cli_vars}
    return final_rules, vars_map, all_rules


def rules_markdown(
    args: list[str] | None = None,
    work_dir: Path | None = None,
    default_target: str = "default",
    prog: str | None = None,
) -> str:
    final_rules, vars_map, all_rules = resolve_rules_selection(
        args, work_dir=work_dir, default_target=default_target, prog=prog
    )
    block_sections: list[str] = []
    eng_rules: list[str] = []
    eng_labels: list[str] = []
    for r in final_rules:
        body = _render_rule_vars(all_rules[r][1].strip(), vars_map)
        if not body:
            continue
        if r.startswith("blocks/"):
            block_sections.append(body)
        else:
            eng_rules.append(body)
            eng_labels.append(r.rsplit("/", 1)[-1] if r.startswith("core/") else r)

    out_parts: list[str] = []
    if block_sections:
        out_parts.append("\n\n".join(block_sections))
    if eng_rules:
        hdr = f"## Agent Engineering Rules ({', '.join(eng_labels)})"
        out_parts.append(hdr + "\n\n" + "\n".join(eng_rules))
    return "\n\n".join(out_parts)


def agents_markdown(prog: str | None = None, args: list[str] | None = None, work_dir: Path | None = None) -> str:
    return rules_markdown(args=args, work_dir=work_dir, default_target="default", prog=prog)


def cmd_rules(argv: list[str], default_target: str = "default") -> int:
    prog = prog_name()
    if any(a in ("--list", "-l") for a in argv):
        if len(argv) > 1:
            raise SystemExit(f"{prog}: usage: {prog} --agents [ITEM ... | -RULE | KEY=VAL | --list]")
        user_rules = _discover_user_rules()
        presets = _discover_presets()
        rdir = rules_dir_path()
        sys.stdout.write("Presets (logical groups of rules/presets):\n")
        for k, (desc, items) in presets.items():
            sys.stdout.write(f"  {k:<22}  {desc}\n")
            sys.stdout.write(f"  {'':<22}    -> {', '.join(items)}\n")
        sys.stdout.write("  all                     Include all built-in and custom atomic rules\n\n")
        sys.stdout.write("Atomic rules (grouped by category; exclude any rule with -<rule>):\n")
        sys.stdout.write("  blocks                  Auto-select blocks/bash or blocks/pwsh by active shell\n")
        sys.stdout.write("  vcs/auto                Auto-select vcs/git or vcs/cvs by repository directory\n")
        for k, (desc, _) in EMBEDDED_RULES.items():
            override = " (overridden by user file)" if k in user_rules else ""
            sys.stdout.write(f"  {k:<22}  {desc}{override}\n")
        custom_only = {k: v for k, v in user_rules.items() if k not in EMBEDDED_RULES}
        sys.stdout.write(f"\nCustom rule files ({rdir}):\n")
        if custom_only:
            for k, (desc, _) in custom_only.items():
                sys.stdout.write(f"  {k:<22}  {desc}\n")
        else:
            sys.stdout.write("  (none — add <rule>.md files to this directory to define custom rules)\n")
        return 0
    for a in argv:
        if a.startswith("--"):
            raise SystemExit(f"{prog}: usage: {prog} --agents [ITEM ... | -RULE | KEY=VAL | --list]")
    sys.stdout.write(rules_markdown(argv, default_target=default_target) + "\n")
    return 0

RULE_VAR_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*):([^{}]*)\}")


def _render_rule_vars(text: str, vars_map: dict[str, str]) -> str:
    return RULE_VAR_RE.sub(lambda m: vars_map.get(m.group(1), m.group(2)), text)


def agents_markdown(prog: str | None = None) -> str:
    cmd = prog or prog_name()
    b_key = "blocks/pwsh" if _is_powershell() else "blocks/bash"
    body = EMBEDDED_RULES[b_key][1].strip()
    return _render_rule_vars(body, {"cmd": cmd, "version": VERSION})

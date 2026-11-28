#!/usr/bin/env python3
"""CLI entrypoint, build.py, install.sh, self-update, and session state tests."""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

try:
    from tests.helpers import INSTALL_SH, ROOT, SCRIPT, RunBlockTestCase, load_module
except ImportError:
    from helpers import INSTALL_SH, ROOT, SCRIPT, RunBlockTestCase, load_module  # type: ignore[no-redef]


class TestCli(RunBlockTestCase):
    def test_help_and_version(self):
        r = self._run_subprocess([str(SCRIPT), "-h"])
        self._assert_ok(r)
        self.assertIn("Usage:", r.stdout)
        self.assertIn("--plan", r.stdout)
        self.assertIn("--config", r.stdout)
        self.assertIn("-P, --profile NAME", r.stdout)
        self.assertNotIn("--agents", r.stdout)
        self.assertIn("--start", r.stdout)
        self.assertNotIn("--init-start", r.stdout)
        self.assertNotIn("--agents-install", r.stdout)

        rv = self._run_subprocess([str(SCRIPT), "--version"])
        self._assert_ok(rv)
        ver_file = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertEqual(rv.stdout.strip(), f"run {ver_file}")

        # Verify urllib.request and tiktoken are not loaded during normal CLI startup and token counting
        lazy_check = "\n".join([
            "import contextlib, importlib.machinery, importlib.util, io, sys",
            f"loader = importlib.machinery.SourceFileLoader('rb', {str(SCRIPT)!r})",
            "spec = importlib.util.spec_from_loader('rb', loader)",
            "mod = importlib.util.module_from_spec(spec)",
            "loader.exec_module(mod)",
            "mod.count_tokens(b'hello world')",
            "mod.parse_bundle_fragments('===== Prompt =====')",
            "buf = io.StringIO()",
            "with contextlib.redirect_stdout(buf):",
            "    mod.main(['--version'])",
            "assert 'urllib.request' not in sys.modules, 'urllib.request loaded eagerly'",
            "assert 'tiktoken' not in sys.modules, 'tiktoken loaded'",
        ])
        r_lazy = subprocess.run([sys.executable, "-c", lazy_check], capture_output=True, text=True, check=False)
        self.assertEqual(r_lazy.returncode, 0, msg=f"stdout:\n{r_lazy.stdout}\nstderr:\n{r_lazy.stderr}")

    def test_help_layout_width_and_alignment(self):
        import re

        r = self._run_subprocess([str(SCRIPT), "-h"])
        self._assert_ok(r)
        self.assertNotIn("--full", r.stdout)
        sections: dict[str, list[str]] = {}
        current = ""
        for ln in r.stdout.splitlines():
            self.assertLessEqual(self.mod.display_width(ln), 100, ln)
            if ln and not ln.startswith(" "):
                current = ln
                sections[current] = []
            elif ln and current:
                sections[current].append(ln)
        expected_tabular = (
            "Session & Execution Commands:",
            "Inspection & History Commands:",
            "Configuration & Maintenance Commands:",
            "Options:",
            "Environment:",
        )
        self.assertEqual(list(sections), ["Usage:", *expected_tabular])
        all_cols = set()
        for title in expected_tabular:
            with self.subTest(section=title):
                cols = set()
                for ln in sections[title]:
                    m = re.match(r"^  \S.*?\S {2,}(?=\S)", ln)
                    if m:
                        cols.add(m.end())
                        all_cols.add(m.end())
                self.assertEqual(len(cols), 1, cols)
                col = cols.pop()
                for ln in sections[title]:
                    if not re.match(r"^  \S", ln):
                        self.assertEqual(len(ln) - len(ln.lstrip(" ")), col, ln)
        self.assertEqual(len(all_cols), 1, all_cols)
        for title in expected_tabular[:3]:
            for ln in sections[title]:
                if re.match(r"^  \S", ln):
                    label = re.split(r" {2,}", ln.strip(), maxsplit=1)[0]
                    if label not in ("run", "<command> | run"):
                        self.assertFalse(label.startswith("run "), label)
        for dash_arg in ("-", "-c", ""):
            with self.subTest(argv0=dash_arg):
                with unittest.mock.patch.object(self.mod.sys, "argv", [dash_arg]):
                    self.assertEqual(self.mod.prog_name(), "run")

    def test_help_lists_session_inspection_flags(self):
        r = self._run_subprocess([str(SCRIPT), "-h"])
        self._assert_ok(r)
        for flag in (
            "--show [session[/step]]",
            "--filter",
            "--script",
            "--out",
            "--part N",
            "--config [KEY[=VALUE] | --edit | --path]",
            "--update [--check | --force]",
            "-r",
            "--run",
            "-c",
            "--clipboard",
            "RUN_BLOCK_PAGER=cat|inherit",
        ):
            with self.subTest(flag=flag):
                self.assertIn(flag, r.stdout)
        for removed in (
            "--info",
            "--check-update",
            "--no-sandbox",
            "--self-update",
            "--rerun",
            "RUN_BLOCK_BUNDLE_MAX_TOKENS",
            "RUN_BLOCK_FRAGMENT_MAX_TOKENS",
            "RUN_BLOCK_PROGRESS",
        ):
            with self.subTest(removed=removed):
                self.assertNotIn(removed, r.stdout)

    def test_run_reply_cli_routing_and_validation(self):
        self.mod.start_session("s1")
        fence = chr(96) * 3
        reply = (
            "I will inspect the repository status and run checks.\n\n"
            + fence + "bash\n"
            "run s99/7 <<'RUN_BLOCK'\n"
            "echo reply_routed_ok\n"
            "RUN_BLOCK\n"
            + fence + "\n"
        )
        r_pipe = self._run([str(SCRIPT), "-r", "-y", "s1"], input=reply)
        self._assert_ok(r_pipe)
        self.assertIn("╭─ END STEP ", r_pipe.stdout)
        self.assertIn("reply_routed_ok", r_pipe.stdout)
        s1_1_out = (self.tmp / "s1" / "1" / "out").read_text(encoding="utf-8")
        self.assertIn("[s1/1] START", s1_1_out)
        self.assertIn("Note: renumbered from s99/7 to s1/1", s1_1_out)

        r_eq = self._run([str(SCRIPT), "--run=s1", "--headless"], input=reply)
        self._assert_ok(r_eq)
        self.assertIn("[s1/2] START", r_eq.stdout)
        self.assertNotIn("╭─ END STEP ", r_eq.stdout)

        # Clipboard ingestion via -rc, -r -c, and -r --clipboard without opening editor
        for idx_clip, clip_args in enumerate(
            (["-rc", "-y", "s1"], ["-r", "-c", "-y", "s1"], ["-r", "--clipboard", "--headless", "s1"]),
            start=3,
        ):
            with self.subTest(clip_args=clip_args), \
                 unittest.mock.patch.object(self.mod, "clipboard_read_command", return_value=["wl-paste", "--no-newline"]), \
                 unittest.mock.patch.object(self.mod, "read_clipboard_text", return_value=reply), \
                 unittest.mock.patch.object(self.mod, "prompt_reply_in_editor", side_effect=AssertionError("editor should not open")):
                r_clip = self._run_in_process(clip_args)
                self._assert_ok(r_clip)
                out_p = self.tmp / "s1" / str(idx_clip) / "out"
                self.assertTrue(out_p.is_file())
                self.assertIn("reply_routed_ok", out_p.read_text(encoding="utf-8"))

        bad_cases = (
            (["-r", "s1", "s2"], 1, "usage:"),
            (["-rc", "s1", "s2"], 1, "usage:"),
            (["-r", "--bogus"], 1, "usage:"),
            (["--run="], 1, "usage:"),
            (["-c"], 1, "-c/--clipboard requires -r/--run"),
            (["--clipboard"], 1, "-c/--clipboard requires -r/--run"),
            (["-r", "-p", "x"], 1, "cannot be used"),
            (["-rc", "-p", "x"], 1, "cannot be used"),
            (["-r", "bad/name/extra"], 1, "invalid"),
            (["-r", "-y", "s1"], 2, "empty reply"),
        )
        for args, exp_rc, needle in bad_cases:
            with self.subTest(args=args):
                rb = self._run([str(SCRIPT), *args], input="")
                self.assertEqual(rb.returncode, exp_rc, msg=rb.stdout + rb.stderr)
                self.assertIn(needle, rb.stderr)

    def _config_env(self):
        proj = self.tmp / "proj"
        proj.mkdir(exist_ok=True)
        os.environ["RUN_BLOCK_CWD"] = str(proj)
        return self.tmp / ".xdg_config" / "run-block" / "config.json"

    def test_config_cli_get_set_unset_and_overview(self):
        cfg = self._config_env()
        r_path = self._run(["--config", "--path"])
        self._assert_ok(r_path)
        self.assertEqual(r_path.stdout.strip(), str(cfg))
        for assignment in (
            "pager=less",
            "max_fix_attempts=4",
            "profiles.deep.provider=anthropic",
            "profiles.deep.model=opus-x",
            "profiles.deep.api_key_cmd=pass show llm/anthropic",
            "default_profile=deep",
            "roles.plan.max_steps=5",
        ):
            with self.subTest(assignment=assignment):
                self._assert_ok(self._run(["--config", assignment]))
        self.assertEqual(cfg.stat().st_mode & 0o777, 0o600)
        data = json.loads(cfg.read_text(encoding="utf-8"))
        self.assertEqual(data["max_fix_attempts"], 4)
        self.assertEqual(data["roles"], {"plan": {"max_steps": 5}})
        r_get = self._run(["--config", "pager"])
        self._assert_ok(r_get)
        self.assertEqual(r_get.stdout, "less\n")
        r_secret = self._run(["--config", "profiles.deep.api_key_cmd"])
        self._assert_ok(r_secret)
        self.assertEqual(r_secret.stdout, "<redacted>\n")
        r_all = self._run(["--config"])
        self._assert_ok(r_all)
        self.assertRegex(r_all.stdout, r"pager +less  \(config\)")
        self.assertRegex(r_all.stdout, r"shell +bash  \(default\)")
        self.assertIn("deep *  provider=anthropic", r_all.stdout)
        self.assertIn("api_key_cmd=<redacted>", r_all.stdout)
        self.assertNotIn("pass show", r_all.stdout)
        self.assertIn("plan  max_steps=5 (config)", r_all.stdout)
        self.assertIn("Active profile: deep (config)", r_all.stdout)
        self._assert_ok(self._run(["--config", "pager="]))
        self._assert_ok(self._run(["--config", "roles.plan.max_steps="]))
        data = json.loads(cfg.read_text(encoding="utf-8"))
        self.assertNotIn("pager", data)
        self.assertNotIn("roles", data)
        r_dp = self._run(["--config", "default_profile"])
        self._assert_ok(r_dp)
        self.assertEqual(r_dp.stdout, "deep\n")

    def test_config_cli_rejects_invalid_and_nested_mutations(self):
        self._config_env()
        bad_cases = (
            (["--config", "bogus=1"], 1, "unknown config key"),
            (["--config", "profiles.x.colour=red"], 1, "unknown config key"),
            (["--config", "roles.chef.profile=x"], 1, "unknown config key"),
            (["--config", "max_fix_attempts=abc"], 1, "invalid value"),
            (["--config", "a", "b"], 1, "usage:"),
            (["--config", "--bogus"], 1, "usage:"),
            (["--config", "-p", "x"], 1, "cannot be used"),
            (["--config", "default_profile"], 1, "is not set"),
        )
        for args, exp_rc, needle in bad_cases:
            with self.subTest(args=args):
                r = self._run(args)
                self.assertEqual(r.returncode, exp_rc, msg=r.stdout + r.stderr)
                self.assertIn(needle, r.stderr)
        os.environ["IN_RUN_BLOCK"] = "1"
        for args in (["--config", "approve_cmd=true"], ["--config", "--edit"]):
            with self.subTest(nested=args):
                r = self._run(args)
                self.assertEqual(r.returncode, 2, msg=r.stderr)
                self.assertIn("from inside a running block", r.stderr)
        self.assertEqual(self._run(["--config", "pager"]).returncode, 0)

    def test_config_cli_edit_validates_json(self):
        cfg = self._config_env()
        writer = "import json, sys; json.dump({'pager': 'edited'}, open(sys.argv[1], 'w'))"
        with unittest.mock.patch.object(self.mod, "resolve_editor_command", return_value=[sys.executable, "-c", writer]):
            self._assert_ok(self._run(["--config", "--edit"]))
        self.assertEqual(cfg.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self._run(["--config", "pager"]).stdout, "edited\n")
        breaker = "import sys; open(sys.argv[1], 'w').write('{bad')"
        with unittest.mock.patch.object(self.mod, "resolve_editor_command", return_value=[sys.executable, "-c", breaker]):
            r_bad = self._run(["--config", "--edit"])
        self.assertEqual(r_bad.returncode, 1)
        self.assertIn("invalid config file", r_bad.stderr)

    def test_profile_flag_persists_resolved_profile_in_session_meta(self):
        cfg = self._config_env()
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(json.dumps({
            "profiles": {"deep": {"provider": "anthropic", "model": "o"}, "fast": {"provider": "openai", "model": "g"}},
            "roles": {"plan": {"profile": "fast"}},
        }), encoding="utf-8")
        bundle = "Role: plan\n\nhello\n"
        self._assert_ok(self._run(["-P", "deep", "--session", "s5"], input=bundle))
        self.assertEqual(json.loads((self.tmp / "s5" / "meta.json").read_text(encoding="utf-8"))["profile"], "deep")
        self._assert_ok(self._run(["--session", "s6"], input=bundle))
        self.assertEqual(json.loads((self.tmp / "s6" / "meta.json").read_text(encoding="utf-8"))["profile"], "fast")
        self._assert_ok(self._run(["--profile=anthropic:claude-x", "--start", "--session", "s7"], input=bundle))
        self.assertEqual(
            json.loads((self.tmp / "s7" / "meta.json").read_text(encoding="utf-8"))["profile"], "anthropic:claude-x"
        )
        bad_cases = (
            (["-P", "missing", "--session", "s8"], "unknown model profile"),
            (["-P", "deep", "--list"], "only supported when starting a session"),
            (["--profile"], "requires an argument"),
        )
        for args, needle in bad_cases:
            with self.subTest(args=args):
                r = self._run(args, input=bundle)
                self.assertEqual(r.returncode, 1, msg=r.stdout + r.stderr)
                self.assertIn(needle, r.stderr)
        self.assertFalse((self.tmp / "s8").exists())

    def test_done_cli_flags_and_help(self):
        r = self._run_subprocess([str(SCRIPT), "-h"])
        self._assert_ok(r)
        self.assertIn("--done [session] [-m NOTE]", r.stdout)
        self.assertIn("[DONE]", r.stdout)
        self.assertIn("next free step", r.stdout)

        self.mod.start_session("s1")
        bad_cases = (
            (["--done", "nosuch"], "not found"),
            (["--done", "s1", "-m"], "-m requires an argument"),
            (["--done", "s1", "s2"], "usage:"),
            (["--done", "--bogus"], "usage:"),
            (["--done", "-p", "x"], "cannot be used"),
        )
        for args, needle in bad_cases:
            with self.subTest(args=args):
                rb = self._run([str(SCRIPT), *args])
                self.assertEqual(rb.returncode, 1, msg=rb.stdout + rb.stderr)
                self.assertIn(needle, rb.stderr)

        r_open = self._run([str(SCRIPT), "--list"])
        self._assert_ok(r_open)
        self.assertRegex(r_open.stdout, r"s1 .*last: s1/0 \(bundle\)\s+next: s1/1")
        r_done = self._run([str(SCRIPT), "--done", "-y", "s1", "-m", "wrap"])
        self._assert_ok(r_done)
        self.assertIn("[s1] END SESSION", r_done.stdout)
        self.assertIn("Note: wrap", r_done.stdout)
        r_list = self._run([str(SCRIPT), "--list"])
        self._assert_ok(r_list)
        self.assertRegex(r_list.stdout, r"s1 .*\[DONE\]")

    def test_embedded_rules_files_exist(self):
        self.assertFalse((ROOT / "src/bundles").exists())
        ab_txt = (ROOT / ".context.bundle").read_text(encoding="utf-8")
        self.assertNotIn("bundle vitalio/run_block", ab_txt)
        self.assertFalse((ROOT / "agents/blocks/pwsh.md").exists())
        self.assertFalse((ROOT / "install.ps1").exists())
        self.assertFalse((ROOT / "agents/blocks/bash.md").exists())
        self.assertFalse((ROOT / "agents/blocks").exists())
        run_md = (ROOT / "agents/run.md").read_text(encoding="utf-8")
        self.assertIn("## Terminal blocks (`{cmd:run}`)", run_md)
        self.assertIn("ONE BLOCK PER MESSAGE, ALWAYS AT THE VERY END (BATCH COMMANDS INSIDE IT)", run_md)
        self.assertIn("small, targeted patch", run_md)
        self.assertIn("comparable in size to the original block", run_md)
        readme_md = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("small, targeted patches", readme_md)
        self.assertIn('chain: ["vitalio/todo-md"]', readme_md)
        self.assertNotIn('chain: ["todo_md"]', readme_md)
        qs_idx = readme_md.index("## Quick Start")
        tui_idx = readme_md.index("## Interactive TUI & Keyboard Shortcuts")
        ref_idx = readme_md.index("## Step Artifacts & `--fix` Diagnostics")
        cli_idx = readme_md.index("## CLI Reference")
        opts_idx = readme_md.index("### Options")
        env_idx = readme_md.index("## Environment Variables")
        self.assertLess(qs_idx, tui_idx)
        self.assertLess(tui_idx, ref_idx)
        self.assertLess(ref_idx, cli_idx)
        self.assertLess(cli_idx, opts_idx)
        self.assertLess(opts_idx, env_idx)
        quick_start_section = readme_md[qs_idx:tui_idx]
        self.assertNotIn("<session>/<step>/out", quick_start_section)
        self.assertNotIn("similarity >= 0.85", quick_start_section)
        step_ref_section = readme_md[ref_idx:cli_idx]
        self.assertIn("<session>/<step>/out", step_ref_section)
        self.assertIn("similarity >= 0.85", step_ref_section)
        options_section = readme_md[opts_idx:env_idx]
        for flag in ("-r", "--run", "-c", "--clipboard", "-y", "--yes", "--headless", "-p", "--prompt", "--sandbox", "-V", "--version", "-h", "--help"):
            self.assertIn(flag, options_section)
        self.assertNotIn("--no-sandbox", options_section)

    def test_self_update_and_check_update(self):
        bin_dir = self.tmp / "up_bin"
        bin_dir.mkdir()
        installed = bin_dir / "my_block"
        legacy_bin = bin_dir / "run_block"
        shutil.copy2(SCRIPT, installed)
        shutil.copy2(SCRIPT, legacy_bin)
        remote_file = self.tmp / "remote_run"
        cur_v = self.mod.VERSION
        src = SCRIPT.read_text(encoding="utf-8").replace(f'VERSION = "{cur_v}"', 'VERSION = "9.9.9"', 1)
        remote_file.write_text(src, encoding="utf-8")
        url = remote_file.as_uri()

        env = {**os.environ, "RUN_BLOCK_UPDATE_URL": url}
        r_chk = self._run([str(installed), "--update", "--check"], capture_output=True, text=True, env=env, check=False)
        self.assertEqual(r_chk.returncode, 0)
        self.assertIn(f"{cur_v} -> 9.9.9", r_chk.stdout)
        for bad_up in (["--check-update"], ["--self-update"], ["--update", "--check", "--force"], ["--update", "--bogus"]):
            with self.subTest(bad_up=bad_up):
                r_bad_up = self._run(bad_up, env=env)
                self.assertNotEqual(r_bad_up.returncode, 0)

        r_up = self._run([str(installed), "--update"], capture_output=True, text=True, env=env, check=False)
        self.assertEqual(r_up.returncode, 0)
        self.assertIn(f"updated {cur_v} -> 9.9.9", r_up.stdout)
        self.assertFalse(legacy_bin.exists(), "legacy run_block binary should be removed on --update")

        # Invoking --update from legacy run_block binary installs run and removes run_block
        shutil.copy2(SCRIPT, legacy_bin)
        r_leg = self._run([str(legacy_bin), "--update"], capture_output=True, text=True, env=env, check=False)
        self.assertEqual(r_leg.returncode, 0, msg=r_leg.stderr)
        self.assertTrue((bin_dir / "run").is_file())
        self.assertFalse(legacy_bin.exists())

    def test_install_sh_fresh_and_conflict(self):
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        state_base = self.tmp / "inst_state"
        legacy_state = state_base / "run_block"
        (legacy_state / "s1").mkdir(parents=True)
        # Seed a legacy run_block binary with legacy repo marker to verify cutover cleanup
        legacy_bin = bin_dir / "run_block"
        legacy_bin.write_text("#!/usr/bin/env python3\n# run_block-repo: vitalio/run_block\n", encoding="utf-8")
        legacy_bin.chmod(0o755)
        env = {**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin", "XDG_STATE_HOME": str(state_base)}
        env.pop("RUN_BLOCK_DIR", None)
        env.pop("IN_RUN_BLOCK", None)

        r1 = subprocess.run(
            ["sh", str(INSTALL_SH), "--dir", str(bin_dir), "--yes"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        self.assertEqual(r1.returncode, 0, r1.stderr)
        self.assertTrue((bin_dir / "run").is_file())
        self.assertFalse(legacy_bin.exists(), "legacy run_block binary should be removed by install.sh")
        self.assertIn("Installed: run", r1.stdout)
        self.assertIn("Removed legacy binary:", r1.stdout)
        self.assertTrue((state_base / "run-block" / "s1").is_dir())
        self.assertFalse(legacy_state.exists())

        (bin_dir / "run").write_text("#!/bin/sh\necho other_tool\n", encoding="utf-8")
        (bin_dir / "run").chmod(0o755)
        r2 = subprocess.run(
            ["sh", str(INSTALL_SH), "--dir", str(bin_dir), "--yes"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertTrue((bin_dir / "run_block").is_file())
        self.assertIn("Installed: run_block", r2.stdout)

    def test_clean_sessions_and_build_py_check(self):
        r_bhelp = subprocess.run([sys.executable, str(ROOT / "build.py"), "-h"], capture_output=True, text=True, check=False)
        self.assertEqual(r_bhelp.returncode, 0)
        self.assertIn("Usage:", r_bhelp.stdout)
        r_bchk = subprocess.run([sys.executable, str(ROOT / "build.py"), "--check"], capture_output=True, text=True, check=False)
        self.assertEqual(r_bchk.returncode, 0, r_bchk.stderr)

        for idx in range(1, 5):
            sdir = self.tmp / f"s{idx}"
            step1 = sdir / "1"
            step1.mkdir(parents=True)
            (step1 / "block.sh").write_text(f"echo {idx}\n", encoding="utf-8")
            (step1 / "out").write_text(f"out {idx}\n", encoding="utf-8")
            os.utime(sdir, (1000 + idx * 10, 1000 + idx * 10))

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self.mod.cmd_clean(["--keep", "2", "--yes"])
        self.assertEqual(rc, 0)
        self.assertIn("Cleaned 2 session(s)", buf.getvalue())
        self.assertIn("s1 (", buf.getvalue())
        self.assertIn("remaining).", buf.getvalue())
        remaining = sorted(p.name for p in self.tmp.iterdir() if p.is_dir())
        self.assertEqual(remaining, ["s3", "s4"])

        buf_all = io.StringIO()
        with contextlib.redirect_stdout(buf_all):
            rc_all = self.mod.cmd_clean(["--all", "--yes"])
        self.assertEqual(rc_all, 0)
        self.assertEqual([p.name for p in self.tmp.iterdir() if p.is_dir()], [])

    def test_persistent_state_dir_and_prune_controls(self):
        # 1. Default base_dir resolution across POSIX XDG, POSIX fallback, and RUN_BLOCK_DIR
        saved_xdg = os.environ.get("XDG_STATE_HOME")
        fake_home = self.tmp / "fake_home"
        try:
            os.environ.pop("RUN_BLOCK_DIR", None)
            os.environ["XDG_STATE_HOME"] = str(self.tmp / "xdg_state")
            self.assertEqual(
                self.mod.default_base_dir("run_block"),
                self.tmp / "xdg_state" / "run-block",
            )
            self.assertEqual(
                self.mod.default_base_dir("custom_prog"),
                self.tmp / "xdg_state" / "run-block",
            )
            os.environ.pop("XDG_STATE_HOME", None)
            with unittest.mock.patch.object(self.mod.Path, "home", return_value=fake_home):
                self.assertEqual(
                    self.mod.default_base_dir("run_block"),
                    fake_home / ".local" / "state" / "run-block",
                )
            os.environ["RUN_BLOCK_DIR"] = str(self.tmp / "explicit_override")
            self.assertEqual(self.mod.default_base_dir("run_block"), self.tmp / "explicit_override")
        finally:
            os.environ["RUN_BLOCK_DIR"] = str(self.tmp)
            if saved_xdg is None:
                os.environ.pop("XDG_STATE_HOME", None)
            else:
                os.environ["XDG_STATE_HOME"] = saved_xdg

        # 2. Sandbox rules keep persistent BASE_DIR read-only even when Workdir is HOME
        home_dir = Path.home().resolve()
        persistent_bdir = home_dir / ".local" / "state" / "run_block"
        with unittest.mock.patch.object(self.mod.sys, "platform", "darwin"), unittest.mock.patch.object(self.mod.Path, "is_file", return_value=True):
            sb_cmd = self.mod.build_sandbox_exec(["bash", "1.sh"], home_dir, persistent_bdir, "strict")
            self.assertEqual(sb_cmd[0], "/usr/bin/sandbox-exec")
            profile = sb_cmd[2]
            allow_idx = profile.index(f'(allow file-write* (subpath "{home_dir}"))')
            deny_idx = profile.index(f'(deny file-write* (subpath "{persistent_bdir}"))')
            self.assertLess(allow_idx, deny_idx)
            quoted_dir = self.tmp / 'dir"with\\quote'
            sb_quoted = self.mod.build_sandbox_exec(["bash", "1.sh"], quoted_dir, persistent_bdir, "strict")
            self.assertIn('dir\\"with\\\\quote', sb_quoted[2])

        # 3. Create sessions with known sizes and timestamps for --list, --clean, and size warning
        import time as _time
        now = _time.time()
        specs = [
            ("s1", 600, now - 10 * 86400),
            ("s2", 1400, now - 5 * 86400),
            ("s3", 2200, now - 2 * 86400),
            ("s4", 800, now - 60),
        ]
        for name, payload_sz, ts in specs:
            sdir = self.tmp / name
            step1 = sdir / "1"
            step1.mkdir(parents=True)
            f_out = step1 / "out"
            f_out.write_bytes(b"x" * payload_sz)
            os.utime(f_out, (ts, ts))
            os.utime(step1, (ts, ts))
            os.utime(sdir, (ts, ts))

        # --list displays per-session and total storage sizes
        list_buf = io.StringIO()
        with contextlib.redirect_stdout(list_buf):
            self.assertEqual(self.mod.cmd_list(), 0)
        list_out = list_buf.getvalue()
        self.assertIn("600 B", list_out)
        self.assertIn("1.4 KB", list_out)
        self.assertIn("2.1 KB", list_out)
        self.assertIn("Total storage: 4.9 KB (4 session(s))", list_out)

        # Oversized state directory emits warning on stderr when exceeding RUN_BLOCK_MAX_STATE_MB
        saved_max_mb = os.environ.get("RUN_BLOCK_MAX_STATE_MB")
        try:
            self.mod._STATE_WARNED_DIRS.clear()
            os.environ["RUN_BLOCK_MAX_STATE_MB"] = "0.002"
            err_buf = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err_buf):
                self.assertEqual(self.mod.cmd_list(), 0)
            self.assertIn("warning: state directory", err_buf.getvalue())
            self.assertIn("exceeds 0.002 MB limit", err_buf.getvalue())
        finally:
            if saved_max_mb is None:
                os.environ.pop("RUN_BLOCK_MAX_STATE_MB", None)
            else:
                os.environ["RUN_BLOCK_MAX_STATE_MB"] = saved_max_mb

        # --clean --older-than 7 removes s1 (10 days old)
        c1_buf = io.StringIO()
        with contextlib.redirect_stdout(c1_buf):
            self.assertEqual(self.mod.cmd_clean(["--older-than", "7", "--yes"]), 0)
        self.assertIn("Cleaned 1 session(s) (s1 (600 B)", c1_buf.getvalue())
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir() if p.is_dir()), ["s2", "s3", "s4"])

        # --clean --max-size 0.003 removes oldest remaining (s2: 1400 B) so remaining (s3+s4 = 3000 B) <= 3145 B
        c2_buf = io.StringIO()
        with contextlib.redirect_stdout(c2_buf):
            self.assertEqual(self.mod.cmd_clean(["--max-size", "0.003", "--yes"]), 0)
        self.assertIn("Cleaned 1 session(s) (s2 (1.4 KB)", c2_buf.getvalue())
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir() if p.is_dir()), ["s3", "s4"])

        # --clean <session> removes specific session by name
        c3_buf = io.StringIO()
        with contextlib.redirect_stdout(c3_buf):
            self.assertEqual(self.mod.cmd_clean(["s3", "--yes"]), 0)
        self.assertIn("Cleaned 1 session(s) (s3 (2.1 KB)", c3_buf.getvalue())
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir() if p.is_dir()), ["s4"])

    def test_subproject_workdir_resolution_and_overrides(self):
        repo = self.tmp / "monorepo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True)
        (repo / "AGENTS.md").write_text("# Monorepo root\n", encoding="utf-8")

        subproj = repo / "apps" / "canary"
        subproj_nested = subproj / "src"
        subproj_nested.mkdir(parents=True)
        (subproj / ".agents_bundle").write_text("bundle vitalio/agents-rules:default\n", encoding="utf-8")

        regular_subdir = repo / "packages" / "plain"
        regular_subdir.mkdir(parents=True)

        sessions_dir = self.tmp / "b3_sessions"
        base_env = {**os.environ, "RUN_BLOCK_DIR": str(sessions_dir)}
        base_env.pop("RUN_BLOCK_CWD", None)

        # 1. Starting session from nested dir inside a subproject with .agents_bundle keeps subproject root
        r_sub = self._run(
            [str(SCRIPT), "--start", "--session", "s1"],
            input="Role: execute\n",
            capture_output=True,
            text=True,
            cwd=str(subproj_nested),
            env=base_env,
            check=False,
        )
        self.assertEqual(r_sub.returncode, 0, r_sub.stderr)
        s1_hdrs = self.mod.parse_bundle_headers(sessions_dir / "s1")
        self.assertEqual(Path(s1_hdrs["workdir"]).resolve(), subproj.resolve())

        # Subsequent step run from monorepo root still executes in persisted subproject Workdir
        r_sub_step = self._run(
            [str(SCRIPT), "-y", "s1/1"],
            input="pwd\n",
            capture_output=True,
            text=True,
            cwd=str(repo),
            env=base_env,
            check=False,
        )
        self.assertEqual(r_sub_step.returncode, 0, r_sub_step.stderr)
        self.assertIn(str(subproj.resolve()), r_sub_step.stdout)

        # 2. Subproject with AGENTS.md or .context.bundle (without .agents_bundle) also resolves to subproject root
        subproj_agents = repo / "apps" / "docs_sub"
        subproj_agents.mkdir(parents=True)
        (subproj_agents / "AGENTS.md").write_text("# Subproject rules\n", encoding="utf-8")
        r_agents = self._run(
            [str(SCRIPT), "--start", "--session", "s2"],
            input="Role: execute\n",
            capture_output=True,
            text=True,
            cwd=str(subproj_agents),
            env=base_env,
            check=False,
        )
        self.assertEqual(r_agents.returncode, 0, r_agents.stderr)
        s2_hdrs = self.mod.parse_bundle_headers(sessions_dir / "s2")
        self.assertEqual(Path(s2_hdrs["workdir"]).resolve(), subproj_agents.resolve())

        subproj_ctx = repo / "apps" / "ctx_sub"
        subproj_ctx_nested = subproj_ctx / "pkg"
        subproj_ctx_nested.mkdir(parents=True)
        (subproj_ctx / ".context.bundle").write_text("bundle vitalio/agents-rules:default\n", encoding="utf-8")
        r_ctx = self._run(
            [str(SCRIPT), "--start", "--session", "s2_ctx"],
            input="Role: execute\n",
            capture_output=True,
            text=True,
            cwd=str(subproj_ctx_nested),
            env=base_env,
            check=False,
        )
        self.assertEqual(r_ctx.returncode, 0, r_ctx.stderr)
        s2_ctx_hdrs = self.mod.parse_bundle_headers(sessions_dir / "s2_ctx")
        self.assertEqual(Path(s2_ctx_hdrs["workdir"]).resolve(), subproj_ctx.resolve())

        # 3. Regular Git subdir without .agents_bundle or AGENTS.md climbs to Git toplevel
        r_reg = self._run(
            [str(SCRIPT), "--start", "--session", "s3"],
            input="Role: execute\n",
            capture_output=True,
            text=True,
            cwd=str(regular_subdir),
            env=base_env,
            check=False,
        )
        self.assertEqual(r_reg.returncode, 0, r_reg.stderr)
        s3_hdrs = self.mod.parse_bundle_headers(sessions_dir / "s3")
        self.assertEqual(Path(s3_hdrs["workdir"]).resolve(), repo.resolve())

        # 4. RUN_BLOCK_CWD=cwd forces exact $PWD even inside subproject
        env_cwd = {**base_env, "RUN_BLOCK_CWD": "cwd"}
        r_cwd = self._run(
            [str(SCRIPT), "--start", "--session", "s4"],
            input="Role: execute\n",
            capture_output=True,
            text=True,
            cwd=str(subproj_nested),
            env=env_cwd,
            check=False,
        )
        self.assertEqual(r_cwd.returncode, 0, r_cwd.stderr)
        s4_hdrs = self.mod.parse_bundle_headers(sessions_dir / "s4")
        self.assertEqual(Path(s4_hdrs["workdir"]).resolve(), subproj_nested.resolve())

        # 5. Explicit RUN_BLOCK_CWD=/path overrides subproject and session Workdir
        explicit_dir = self.tmp / "explicit_target"
        explicit_dir.mkdir()
        env_exp = {**base_env, "RUN_BLOCK_CWD": str(explicit_dir)}
        r_exp = self._run(
            [str(SCRIPT), "--start", "--session", "s5"],
            input="Role: execute\n",
            capture_output=True,
            text=True,
            cwd=str(subproj_nested),
            env=env_exp,
            check=False,
        )
        self.assertEqual(r_exp.returncode, 0, r_exp.stderr)
        s5_hdrs = self.mod.parse_bundle_headers(sessions_dir / "s5")
        self.assertEqual(Path(s5_hdrs["workdir"]).resolve(), explicit_dir.resolve())

    def test_nested_in_run_block_subcommand_guards(self):
        # Create an initial session and step so retry/fix/show/list/sandbox have targets
        self._assert_ok(self._run(["--start", "--session", "s1"], input="Task: F79\n\nhello\n"))
        self._assert_ok(self._run(["-y", "s1/1"], input="echo first\n"))

        nested_env = {
            **os.environ,
            "IN_RUN_BLOCK": "1",
            "RUN_BLOCK_PARENT_SESSION": "s1",
            "RUN_BLOCK_PARENT_STEP": "1",
        }

        # 1. Nested step execution (<session>/<step>, --fix, --retry) is rejected with exit 2
        for label, argv, stdin_payload in (
            ("step", ["s1/2"], "echo nested\n"),
            ("fix", ["--fix", "s1/1"], "text = text.replace('first', 'second')\n"),
            ("retry", ["--retry", "s1/1"], ""),
            ("retry_implicit", ["--retry"], ""),
        ):
            with self.subTest(case=label):
                proc = self._run(argv, input=stdin_payload, env=nested_env)
                self.assertEqual(proc.returncode, 2, msg=proc.stderr)
                self.assertIn("cannot run", proc.stderr)
                self.assertIn("from inside a running block (active step: s1/1)", proc.stderr)

        # 2. Read-only subcommands (--list, --show, --bundle-plan, --plan, --sandbox) succeed
        r_list = self._run(["--list", "s1"], env=nested_env)
        self._assert_ok(r_list)
        self.assertIn("Blocks in s1", r_list.stdout)

        r_show = self._run(["--show", "s1/1"], env=nested_env)
        self._assert_ok(r_show)
        self.assertIn("echo first", r_show.stdout)

        r_bplan = self._run(["--bundle-plan", "s1"], env=nested_env)
        self._assert_ok(r_bplan)
        self.assertIn("[total]", r_bplan.stdout)

        r_plan = self._run(["--plan"], input="echo safe\n", env=nested_env)
        self._assert_ok(r_plan)
        self.assertIn('"operations"', r_plan.stdout)

        r_sb_ro = self._run(["--sandbox"], env=nested_env)
        self._assert_ok(r_sb_ro)
        self.assertIn("Session: s1", r_sb_ro.stdout)

        # Sandbox mutation remains rejected with exit 2
        r_sb_mut = self._run(["--sandbox", "strict", "s1"], env=nested_env)
        self.assertEqual(r_sb_mut.returncode, 2)
        self.assertIn("cannot modify session sandbox settings from inside a running block", r_sb_mut.stderr)

        # 3. Session initialization (--start and piped bundle) is rejected inside IN_RUN_BLOCK=1 with exit 2
        for start_argv in (["--start", "--session", "s2"], [], ["-p", "nested prompt"]):
            with self.subTest(start_argv=start_argv):
                r_start_nested = self._run(start_argv, input="Task: F108\n\nbody\n", env=nested_env)
                self.assertEqual(r_start_nested.returncode, 2, msg=r_start_nested.stderr)
                self.assertIn("cannot start a new session from inside a running block", r_start_nested.stderr)
        self.assertFalse((self.tmp / "s2").exists())

        # 4. Removed aliases (--bundle, --rerun, --self-update, --no-sandbox, --info, --check-update) are rejected
        for removed_argv in (
            ["--bundle"],
            ["--rerun", "s1/1"],
            ["--self-update"],
            ["--no-sandbox", "s1/1"],
            ["--start", "--no-sandbox"],
            ["--info", "s1"],
            ["--check-update"],
        ):
            with self.subTest(removed_argv=removed_argv):
                r_rem = self._run(removed_argv)
                self.assertNotEqual(r_rem.returncode, 0)

    def test_state_migration_live_step_symlink_and_workdir_fallback(self):
        xdg = self.tmp / "state_mig"
        legacy = xdg / "run_block"
        target = xdg / "run-block"
        (legacy / "s1" / "1").mkdir(parents=True)
        (legacy / "s1" / "0").write_text("Session: s1\n", encoding="utf-8")

        os.environ.pop("RUN_BLOCK_DIR", None)
        os.environ["XDG_STATE_HOME"] = str(xdg)
        os.environ["IN_RUN_BLOCK"] = "1"
        try:
            # 1. Inside live step (IN_RUN_BLOCK=1): os.replace migrates to run-block and leaves symlink run_block -> run-block
            resolved = self.mod.default_base_dir()
            self.assertEqual(resolved, target)
            self.assertTrue(target.is_dir())
            self.assertFalse(target.is_symlink())
            self.assertTrue(legacy.is_symlink())
            self.assertEqual(os.readlink(legacy), "run-block")
            # Parent process writing via legacy path reaches migrated target
            (legacy / "s1" / "1" / "out").write_text("ok_from_parent\n", encoding="utf-8")
            self.assertEqual((target / "s1" / "1" / "out").read_text(encoding="utf-8"), "ok_from_parent\n")

            # 2. Subsequent outer invocation (IN_RUN_BLOCK!=1) cleans up transitional symlink
            os.environ.pop("IN_RUN_BLOCK", None)
            resolved_outer = self.mod.default_base_dir()
            self.assertEqual(resolved_outer, target)
            self.assertFalse(legacy.exists())
            self.assertFalse(legacy.is_symlink())
            self.assertTrue((target / "s1" / "1" / "out").is_file())
        finally:
            os.environ.pop("IN_RUN_BLOCK", None)
            os.environ["RUN_BLOCK_DIR"] = str(self.tmp)

        # 3. Hyphen/underscore fallback in _resolve_existing_dir()
        renamed_hyphen = self.tmp / "my-checkout"
        renamed_hyphen.mkdir()
        self.assertEqual(
            self.mod._resolve_existing_dir(str(self.tmp / "my_checkout")),
            renamed_hyphen.resolve(),
        )
        renamed_under = self.tmp / "other_repo"
        renamed_under.mkdir()
        self.assertEqual(
            self.mod._resolve_existing_dir(str(self.tmp / "other-repo")),
            renamed_under.resolve(),
        )

    def test_uninstall_and_purge_cli_and_install_sh(self):
        bin_dir = self.tmp / "uninst_bin"
        bin_dir.mkdir()
        state_parent = self.tmp / "uninst_state"
        state_dir = state_parent / "run-block"
        (state_dir / "s1").mkdir(parents=True)
        (state_dir / "s1" / "0").write_text("Session: s1\n", encoding="utf-8")

        # Install both run_block and run plus a foreign binary
        shutil.copy2(SCRIPT, bin_dir / "run_block")
        shutil.copy2(SCRIPT, bin_dir / "run")
        foreign = bin_dir / "other_tool"
        foreign.write_text("#!/bin/sh\necho foreign\n", encoding="utf-8")
        foreign.chmod(0o755)

        env = {
            **os.environ,
            "RUN_BLOCK_INSTALL_DIR": str(bin_dir),
            "XDG_STATE_HOME": str(state_parent),
        }
        env.pop("RUN_BLOCK_DIR", None)

        # 1. CLI --uninstall removes run and run_block but preserves state and foreign tool
        r_un = self._run([str(bin_dir / "run_block"), "--uninstall"], env=env)
        self._assert_ok(r_un)
        self.assertIn("Removed:", r_un.stdout)
        self.assertFalse((bin_dir / "run_block").exists())
        self.assertFalse((bin_dir / "run").exists())
        self.assertTrue(foreign.is_file())
        self.assertTrue(state_dir.is_dir())

        # 2. Re-copy and run CLI --uninstall --purge -> removes binary and state directory
        shutil.copy2(SCRIPT, bin_dir / "run")
        r_purge = self._run([str(bin_dir / "run"), "--uninstall", "--purge"], env=env)
        self._assert_ok(r_purge)
        self.assertFalse((bin_dir / "run").exists())
        self.assertFalse(state_dir.exists())

        # 3. install.sh --uninstall and --uninstall --purge
        (state_dir / "s2").mkdir(parents=True)
        r_inst = subprocess.run(
            ["sh", str(INSTALL_SH), "--dir", str(bin_dir), "--yes"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        self._assert_ok(r_inst)
        self.assertTrue((bin_dir / "run").is_file())

        r_sh_un = subprocess.run(
            ["sh", str(INSTALL_SH), "--dir", str(bin_dir), "--uninstall"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        self._assert_ok(r_sh_un)
        self.assertIn("Removed:", r_sh_un.stdout)
        self.assertFalse((bin_dir / "run").exists())
        self.assertTrue(state_dir.is_dir())

        shutil.copy2(SCRIPT, bin_dir / "run_block")
        r_sh_purge = subprocess.run(
            ["sh", str(INSTALL_SH), "--dir", str(bin_dir), "--uninstall", "--purge"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        self._assert_ok(r_sh_purge)
        self.assertFalse((bin_dir / "run_block").exists())
        self.assertFalse(state_dir.exists())


if __name__ == "__main__":
    unittest.main()

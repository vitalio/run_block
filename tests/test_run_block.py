#!/usr/bin/env python3
"""Tests for run_block and install.sh."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import shutil
import subprocess
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run_block"
INSTALL_SH = ROOT / "install.sh"


def load_module():
    loader = importlib.machinery.SourceFileLoader("run_block", str(SCRIPT))
    spec = importlib.util.spec_from_loader("run_block", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class TestRunBlock(unittest.TestCase):
    def setUp(self):
        self._orig_env = {
            k: os.environ.get(k)
            for k in (
                "RUN_BLOCK_NO_CLIPBOARD",
                "RUN_BLOCK_CLIPBOARD",
                "RUN_BLOCK_CONFIRM",
                "RUN_BLOCK_CONFIG",
                "RUN_BLOCK_DIR",
                "RUN_BLOCK_CWD",
                "IN_RUN_BLOCK",
                "RUN_BLOCK_UPDATE_URL",
                "RUN_BLOCK_SHELL",
                "RUN_BLOCK_SAFETY_DISABLE",
                "RUN_BLOCK_SAFETY_RULES",
                "RUN_BLOCK_APPROVE_CMD",
                "RUN_BLOCK_HEADLESS",
            )
        }
        os.environ["RUN_BLOCK_NO_CLIPBOARD"] = "1"
        os.environ.pop("IN_RUN_BLOCK", None)
        self.tmp = Path(tempfile.mkdtemp(prefix="rb_test_"))
        os.environ["RUN_BLOCK_DIR"] = str(self.tmp)
        self.mod = load_module()
        self.mod.BASE_DIR = self.tmp

    def tearDown(self):
        for k, v in self._orig_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_help_and_version(self):
        r = subprocess.run([str(SCRIPT), "-h"], capture_output=True, text=True, check=False)
        self.assertEqual(r.returncode, 0)
        self.assertIn("Usage:", r.stdout)
        self.assertIn("--plan", r.stdout)
        self.assertNotIn("--config", r.stdout)
        self.assertIn("--agents", r.stdout)
        self.assertIn("--start", r.stdout)
        self.assertNotIn("--init-start", r.stdout)
        self.assertNotIn("--agents-install", r.stdout)

        rv = subprocess.run([str(SCRIPT), "--version"], capture_output=True, text=True, check=False)
        self.assertEqual(rv.returncode, 0)
        ver_file = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertEqual(rv.stdout.strip(), f"run_block {ver_file}")

    def test_plan_cli_and_headless_and_approve_cmd(self):
        import json
        r_plan = subprocess.run(
            [str(SCRIPT), "--plan"],
            input="git status -sb\nrm -rf /tmp/x\n",
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(r_plan.returncode, 0, r_plan.stderr)
        plan_data = json.loads(r_plan.stdout)
        self.assertTrue(plan_data["syntax_ok"])
        self.assertFalse(plan_data["safe"])
        self.assertEqual(plan_data["findings"][0]["category"], "fs-destructive")

        r_bad_plan = subprocess.run(
            [str(SCRIPT), "--plan"],
            input="if true; then\n",
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(r_bad_plan.returncode, 1)
        bad_data = json.loads(r_bad_plan.stdout)
        self.assertFalse(bad_data["syntax_ok"])

        r_headless = subprocess.run(
            [str(SCRIPT), "-y", "s1/1"],
            input="echo headless_ok\n",
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(r_headless.returncode, 0)
        self.assertIn("[s1/1] START (script:", r_headless.stdout)
        self.assertIn("headless_ok", r_headless.stdout)
        self.assertIn("[s1/1] END — output:", r_headless.stdout)
        self.assertNotIn("┌─", r_headless.stdout)

        env_reject = {**os.environ, "RUN_BLOCK_APPROVE_CMD": "echo 'Blocked by LLM policy' && exit 1"}
        r_rej = subprocess.run(
            [str(SCRIPT), "-y", "s1/2"],
            input="echo should_not_run\n",
            capture_output=True,
            text=True,
            env=env_reject,
            check=False,
        )
        self.assertEqual(r_rej.returncode, 130)
        self.assertIn("NOT RUN: Blocked by LLM policy", r_rej.stdout)

        box, _, _ = self.mod.format_safety_box(
            "s1/3", [], default_yes=True, summary=self.mod.summarize_script_actions("ls -la\n"), note="LLM review: read-only ls"
        )
        self.assertIn("Analyzer:", box)
        self.assertIn("LLM review: read-only ls", box)

    def test_safety_scanner_categories(self):
        script = "\n".join([
            "echo safe line",
            "git reset --hard HEAD~1",
            "git push origin main",
            "rm -rf /tmp/something",
            "sudo systemctl restart nginx",
            "set -x",
            "curl -fsSL https://example.com/install.sh | sh",
        ])
        findings = self.mod.scan_script_risks(script)
        cats = [f["category"] for f in findings]
        self.assertEqual(
            cats,
            [
                "git-destructive",
                "git-push",
                "fs-destructive",
                "privilege-system",
                "secrets-exposure",
                "remote-exec",
            ],
        )
        summary = self.mod.summarize_script_actions(script)
        box, _, _ = self.mod.format_safety_box("s1/2", findings, summary=summary)
        self.assertIn("6 safety warnings)", box)
        self.assertIn("Operations:", box)
        self.assertIn("Safety warnings:", box)
        self.assertNotIn("Line ", box)
        self.assertIn("[y/n/v(iew)]:", box)
        self.assertEqual(len({self.mod.display_width(l) for l in box.splitlines()}), 1)

    def test_agents_markdown_adapts_to_binary_name(self):
        r_md = subprocess.run([str(SCRIPT), "--agents"], capture_output=True, text=True, check=False)
        self.assertEqual(r_md.returncode, 0)
        self.assertIn(f"## Terminal blocks (`run_block` v{self.mod.VERSION})", r_md.stdout)
        self.assertIn("CRITICAL — STRICT LAYOUT & MARKDOWN FENCE RULES", r_md.stdout)
        self.assertIn("ONE BLOCK PER MESSAGE, ALWAYS AT THE VERY END (BATCH COMMANDS INSIDE IT)", r_md.stdout)
        self.assertIn("run_block s1/1 <<'RUN_BLOCK'", r_md.stdout)
        self.assertNotIn("/tmp/", r_md.stdout)

        custom_bin = self.tmp / "run_term_block"
        shutil.copy2(SCRIPT, custom_bin)
        env = {**os.environ}
        env.pop("RUN_BLOCK_DIR", None)
        rc_md = subprocess.run([str(custom_bin), "--agents"], capture_output=True, text=True, env=env, check=False)
        self.assertEqual(rc_md.returncode, 0)
        self.assertIn("## Terminal blocks (`run_term_block`", rc_md.stdout)
        self.assertIn("run_term_block s1/1 <<'RUN_BLOCK'", rc_md.stdout)
    def test_start_autoincrement(self):
        s1 = self.mod.start_session()
        s2 = self.mod.start_session()
        self.assertEqual(s1.name, "s1")
        self.assertEqual(s2.name, "s2")

    def test_normal_execution_and_duplicate_guard(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc1 = self.mod.cmd_normal("s1/1", "echo hello_world in_rb=$IN_RUN_BLOCK\n")
            self.assertEqual(rc1, 0)
            rc_dup = self.mod.cmd_normal("s1/1", "echo again\n")
            self.assertEqual(rc_dup, 2)
            rc_skip = self.mod.cmd_normal("s1/3", "echo step3\n")
            self.assertEqual(rc_skip, 2)
        out1 = (self.tmp / "s1/1.txt").read_text(encoding="utf-8")
        self.assertIn("hello_world in_rb=1", out1)
        self.assertIn("[s1/1] END — output:", out1)
        self.assertIn("┌─ s1/1 · END ", buf.getvalue())
        self.assertIn("┌─ s1/3 · NOT RUN ", buf.getvalue())

    def test_failed_execution_and_chained_fixes(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self.mod.cmd_normal("s1/1", "echo bad_cmd\nexit 3\n")
            self.assertEqual(rc, 3)
            bad_fix = "assert False\n"
            self.assertEqual(self.mod.cmd_fix("s1/1", bad_fix), 2)
            fix1 = "text = text.replace('exit 3', 'exit 4')\n"
            self.assertEqual(self.mod.cmd_fix("s1/1", fix1), 4)
            self.assertEqual(self.mod.cmd_fix("s1/1", fix1), 2)
            fix2 = "text = text.replace('exit 4', 'echo fixed_ok')\n"
            self.assertEqual(self.mod.cmd_fix("s1/1_1", fix2), 0)
        out_f2 = (self.tmp / "s1/1_2.txt").read_text(encoding="utf-8")
        self.assertIn("fixed_ok", out_f2)

    def test_syntax_error_does_not_run(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self.mod.cmd_normal("s1/1", "if true; then\n")
        self.assertNotEqual(rc, 0)
        out = (self.tmp / "s1/1.txt").read_text(encoding="utf-8")
        self.assertIn("END (syntax error", out)
        box_lines = buf.getvalue().strip().splitlines()
        self.assertEqual(len({self.mod.display_width(l) for l in box_lines}), 1)

    def test_stats_and_clipboard_box(self):
        f = self.tmp / "x.txt"
        f.write_text("hello\n", encoding="utf-8")
        s = self.mod.stats_line(f)
        self.assertIn("Size: 6 bytes", s)
        self.assertIn("Claude", s)
        box, _, _ = self.mod.format_clipboard_box("s2/1", f, stats=s)
        lines = box.splitlines()
        self.assertEqual(len(lines), 4)
        self.assertEqual(len({self.mod.display_width(l) for l in lines}), 1)

    def test_self_update_and_check_update(self):
        installed = self.tmp / "my_block"
        shutil.copy2(SCRIPT, installed)
        remote_file = self.tmp / "remote_run_block"
        cur_v = self.mod.VERSION
        src = SCRIPT.read_text(encoding="utf-8").replace(f'VERSION = "{cur_v}"', 'VERSION = "9.9.9"', 1)
        remote_file.write_text(src, encoding="utf-8")
        url = remote_file.as_uri()

        env = {**os.environ, "RUN_BLOCK_UPDATE_URL": url}
        r_chk = subprocess.run([str(installed), "--check-update"], capture_output=True, text=True, env=env, check=False)
        self.assertEqual(r_chk.returncode, 0)
        self.assertIn(f"{cur_v} -> 9.9.9", r_chk.stdout)

        r_up = subprocess.run([str(installed), "--update"], capture_output=True, text=True, env=env, check=False)
        self.assertEqual(r_up.returncode, 0)
        self.assertIn(f"updated {cur_v} -> 9.9.9", r_up.stdout)

    def test_install_sh_fresh_and_conflict(self):
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        env = {**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin"}

        r1 = subprocess.run(
            ["sh", str(INSTALL_SH), "--dir", str(bin_dir), "--yes"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        self.assertEqual(r1.returncode, 0, r1.stderr)
        self.assertTrue((bin_dir / "run_block").is_file())
        self.assertIn("Installed: run_block", r1.stdout)

        (bin_dir / "run_block").write_text("#!/bin/sh\necho other_tool\n", encoding="utf-8")
        (bin_dir / "run_block").chmod(0o755)
        r2 = subprocess.run(
            ["sh", str(INSTALL_SH), "--dir", str(bin_dir), "--yes"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertTrue((bin_dir / "run_term_block").is_file())
        self.assertIn("Installed: run_term_block", r2.stdout)


    def test_list_show_and_retry(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.mod.cmd_normal("s1/1", "echo first_step\n")
        r_list = subprocess.run([str(SCRIPT), "--list"], capture_output=True, text=True, check=False)
        self.assertEqual(r_list.returncode, 0)
        self.assertIn("s1/1", r_list.stdout)
        self.assertIn("END)", r_list.stdout)

        r_show = subprocess.run([str(SCRIPT), "--show", "s1/1"], capture_output=True, text=True, check=False)
        self.assertEqual(r_show.returncode, 0)
        self.assertIn("echo first_step", r_show.stdout)

        r_retry = subprocess.run([str(SCRIPT), "--retry", "s1/1"], capture_output=True, text=True, check=False)
        self.assertEqual(r_retry.returncode, 0)
        self.assertIn("first_step", r_retry.stdout)

    def test_stdin_start_bundle_without_args_and_with_start_flag(self):
        proj = self.tmp / "proj"
        proj.mkdir()
        env = {**os.environ, "RUN_BLOCK_DIR": str(self.tmp / "sessions"), "RUN_BLOCK_CWD": str(proj)}

        bundle_input = "===== File: AGENTS.md =====\n# My Project Rules\n\n===== Prompt =====\nWork on task F1\n"
        r_pipe = subprocess.run(
            [str(SCRIPT)],
            input=bundle_input,
            capture_output=True,
            text=True,
            cwd=str(proj),
            env=env,
            check=False,
        )
        self.assertEqual(r_pipe.returncode, 0, r_pipe.stderr)
        self.assertIn("Session: s1", r_pipe.stdout)
        self.assertIn("Next block: s1/1", r_pipe.stdout)
        bundle1 = (self.tmp / "sessions/s1/0.txt").read_text(encoding="utf-8")
        self.assertIn("Session: s1\nNext block: s1/1\nWorkdir:", bundle1)
        self.assertIn("===== File: AGENTS.md =====", bundle1)
        self.assertIn("Work on task F1", bundle1)

        r_step1 = subprocess.run(
            [str(SCRIPT), "s1/1"],
            input="echo ran_s1_step1\n",
            capture_output=True,
            text=True,
            cwd=str(proj),
            env=env,
            check=False,
        )
        self.assertEqual(r_step1.returncode, 0, r_step1.stderr)
        self.assertIn("s1/1 · END", r_step1.stdout)
        self.assertIn("ran_s1_step1", r_step1.stdout)

        r_start = subprocess.run(
            [str(SCRIPT), "--start", "--session", "s2"],
            input=bundle_input,
            capture_output=True,
            text=True,
            cwd=str(proj),
            env=env,
            check=False,
        )
        self.assertEqual(r_start.returncode, 0, r_start.stderr)
        self.assertIn("Session: s2", r_start.stdout)

        r_show0 = subprocess.run(
            [str(SCRIPT), "--show", "s2/0"],
            capture_output=True,
            text=True,
            cwd=str(proj),
            env=env,
            check=False,
        )
        self.assertEqual(r_show0.returncode, 0)
        self.assertIn("Bundle:", r_show0.stdout)

    def test_info_and_prompt_boxes_and_skipped_step_confirmation(self):
        info_box = self.mod.format_info_box("s1/0 · START BUNDLE", ["Session: s1", "Next block: s1/1"])
        self.assertIn("┌─ s1/0 · START BUNDLE ", info_box)
        self.assertEqual(len({self.mod.display_width(l) for l in info_box.splitlines()}), 1)

        p_box, _, _ = self.mod.format_prompt_box(
            "s1/2 · MISSING PREVIOUS STEP",
            ["Previous step s1/1 has not been run yet."],
            "-> Run s1/2 anyway? [y/N]: ",
        )
        self.assertIn("MISSING PREVIOUS STEP", p_box)
        self.assertEqual(len({self.mod.display_width(l) for l in p_box.splitlines()}), 1)

        tty_w = io.StringIO()
        tty_r = io.StringIO("y\n")
        ok = self.mod.prompt_yes_no_box(
            "s1/2 · MISSING PREVIOUS STEP",
            ["Previous step s1/1 has not been run yet."],
            "Run s1/2 anyway?",
            default_yes=False,
            tty_streams=(tty_w, tty_r),
        )
        self.assertTrue(ok)
        self.assertIn("✓ Confirmed by user.", tty_w.getvalue())

    def test_powershell_mode_and_agents(self):
        fake_pwsh = self.tmp / "pwsh"
        fake_pwsh.write_text(
            "#!/bin/sh\n"
            "if [ \"$3\" = \"-Command\" ]; then\n"
            "  grep -q 'SYNTAX_ERR' \"$5\" && { echo 'ParseError: missing closing brace' >&2; exit 1; }\n"
            "  exit 0\n"
            "fi\n"
            "if [ \"$2\" = \"-File\" ]; then\n"
            "  sh \"$3\"\n"
            "  exit $?\n"
            "fi\n"
            "exit 0\n",
            encoding="utf-8",
        )
        fake_pwsh.chmod(0o755)
        os.environ["RUN_BLOCK_SHELL"] = str(fake_pwsh)
        try:
            self.assertTrue(self.mod._is_powershell())
            self.assertEqual(self.mod._script_ext(), ".ps1")
            md = self.mod.agents_markdown("run_block")
            self.assertIn("powershell", md)
            self.assertIn("'@ | run_block s1/1", md)
            self.assertIn("fresh `pwsh` process", md)

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc_ok = self.mod.cmd_normal("s1/1", "echo ps1_ran_ok\n")
                self.assertEqual(rc_ok, 0)
                self.assertTrue((self.tmp / "s1/1.ps1").is_file())
                rc_err = self.mod.cmd_normal("s1/2", "echo SYNTAX_ERR\n")
                self.assertNotEqual(rc_err, 0)
                rc_fix = self.mod.cmd_fix("s1/2", "text = text.replace('SYNTAX_ERR', 'fixed_ps1')\n")
                self.assertEqual(rc_fix, 0)
                self.assertTrue((self.tmp / "s1/2_1.ps1").is_file())
            self.assertIn("ps1_ran_ok", (self.tmp / "s1/1.txt").read_text(encoding="utf-8"))
            self.assertIn("fixed_ps1", (self.tmp / "s1/2_1.txt").read_text(encoding="utf-8"))
        finally:
            os.environ.pop("RUN_BLOCK_SHELL", None)

    def test_custom_safety_rules_and_disable(self):
        os.environ["RUN_BLOCK_SAFETY_DISABLE"] = "external-write"
        os.environ["RUN_BLOCK_SAFETY_RULES"] = r"prod-db=\bpsql\b.*prod; privilege-system=\bsudo\s+reboot\b"
        try:
            script = "\n".join([
                "git push origin main",
                "sudo apt install htop",
                "sudo reboot",
                "psql -h prod.db.internal",
            ])
            findings = self.mod.scan_script_risks(script)
            cats = [f["category"] for f in findings]
            self.assertNotIn("git-push", cats)
            self.assertEqual(cats, ["privilege-system", "prod-db"])
        finally:
            os.environ.pop("RUN_BLOCK_SAFETY_DISABLE", None)
            os.environ.pop("RUN_BLOCK_SAFETY_RULES", None)

    def test_clean_sessions_and_build_py_check(self):
        r_bhelp = subprocess.run(["python3", str(ROOT / "build.py"), "-h"], capture_output=True, text=True, check=False)
        self.assertEqual(r_bhelp.returncode, 0)
        self.assertIn("Usage:", r_bhelp.stdout)
        r_bchk = subprocess.run(["python3", str(ROOT / "build.py"), "--check"], capture_output=True, text=True, check=False)
        self.assertEqual(r_bchk.returncode, 0, r_bchk.stderr)

        for idx in range(1, 5):
            sdir = self.tmp / f"s{idx}"
            sdir.mkdir()
            (sdir / "1.sh").write_text(f"echo {idx}\n", encoding="utf-8")
            (sdir / "1.txt").write_text(f"out {idx}\n", encoding="utf-8")
            os.utime(sdir, (1000 + idx * 10, 1000 + idx * 10))

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self.mod.cmd_clean(["--keep", "2", "--yes"])
        self.assertEqual(rc, 0)
        self.assertIn("Cleaned 2 session(s)", buf.getvalue())
        remaining = sorted(p.name for p in self.tmp.iterdir() if p.is_dir())
        self.assertEqual(remaining, ["s3", "s4"])

        buf_all = io.StringIO()
        with contextlib.redirect_stdout(buf_all):
            rc_all = self.mod.cmd_clean(["--all", "--yes"])
        self.assertEqual(rc_all, 0)
        self.assertEqual([p.name for p in self.tmp.iterdir() if p.is_dir()], [])


    def test_heredoc_collapsed_in_block_plan(self):
        rb_mod = load_module()
        script = (
            "cat <<'EOF' > src/example.py\n"
            + "\n".join(f"line_{i} = {i}" for i in range(40))
            + "\nEOF\n"
            "git status -sb\n"
        )
        summary = rb_mod.summarize_script_actions(script, Path("/tmp"))
        ops = summary["operations"]
        self.assertEqual(len(ops), 2)
        self.assertEqual(ops[0][0], "write")
        self.assertIn("cat <<'EOF' > src/example.py (40 lines)", ops[0][1])
        self.assertEqual(ops[1], ("git", "git status -sb"))

        multi_cd = "cd /tmp\nls -la\ncd /var\nls -la\n"
        sum_cd = rb_mod.summarize_script_actions(multi_cd, Path("/home"))
        box_cd, _, _ = rb_mod.format_safety_box("s1/4", [], default_yes=True, summary=sum_cd)
        self.assertIn("┌─ s1/4 · BLOCK PLAN ", box_cd)
        self.assertIn("│   /tmp:", box_cd)
        stripped_lines = [l.strip("│ ") for l in box_cd.splitlines()]
        idx_var = stripped_lines.index("/var:")
        self.assertEqual(stripped_lines[idx_var - 1], "")


if __name__ == "__main__":
    unittest.main()

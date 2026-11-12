#!/usr/bin/env python3
"""Tests for run_block and install.sh."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import shutil
import subprocess
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
            )
        }
        os.environ["RUN_BLOCK_NO_CLIPBOARD"] = "1"
        os.environ.pop("IN_RUN_BLOCK", None)
        self.tmp = Path(tempfile.mkdtemp(prefix="rb_test_"))
        os.environ["RUN_BLOCK_DIR"] = str(self.tmp)
        os.environ["RUN_BLOCK_CONFIG"] = str(self.tmp / "config")
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
        self.assertIn("--config", r.stdout)
        self.assertIn("--agents", r.stdout)
        self.assertIn("--agents-install", r.stdout)

        rv = subprocess.run([str(SCRIPT), "--version"], capture_output=True, text=True, check=False)
        self.assertEqual(rv.returncode, 0)
        ver_file = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertEqual(rv.stdout.strip(), f"run_block {ver_file}")

    def test_config_init_and_precedence(self):
        cfg_file = self.tmp / "custom_config"
        env = {**os.environ, "RUN_BLOCK_CONFIG": str(cfg_file)}
        env.pop("RUN_BLOCK_DIR", None)
        env.pop("RUN_BLOCK_CONFIRM", None)

        r_init = subprocess.run([str(SCRIPT), "--init-config"], capture_output=True, text=True, env=env, check=False)
        self.assertEqual(r_init.returncode, 0)
        self.assertTrue(cfg_file.is_file())

        # Write custom settings to config file
        cfg_file.write_text("work_dir = cwd\ntoken_stats = false\n", encoding="utf-8")
        r_cfg = subprocess.run([str(SCRIPT), "--config"], capture_output=True, text=True, env=env, check=False)
        self.assertEqual(r_cfg.returncode, 0)
        self.assertIn("work_dir     = cwd  (from config)", r_cfg.stdout)
        self.assertIn("token_stats  = false  (from config)", r_cfg.stdout)

        # Env var overrides config file
        env["RUN_BLOCK_CWD"] = "/tmp"
        r_cfg2 = subprocess.run([str(SCRIPT), "--config"], capture_output=True, text=True, env=env, check=False)
        self.assertIn("work_dir     = /tmp  (from env)", r_cfg2.stdout)

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
                "external-write",
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
        self.assertIn("[y/n]:", box)
        self.assertEqual(len({self.mod.display_width(l) for l in box.splitlines()}), 1)

    def test_agents_markdown_adapts_to_binary_name(self):
        r_md = subprocess.run([str(SCRIPT), "--agents"], capture_output=True, text=True, check=False)
        self.assertEqual(r_md.returncode, 0)
        self.assertIn(f"## Terminal blocks (`run_block` v{self.mod.VERSION})", r_md.stdout)
        self.assertIn("CRITICAL — ONE BLOCK PER MESSAGE:", r_md.stdout)
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
        rc1 = self.mod.cmd_normal("s1/1", "echo hello_world in_rb=$IN_RUN_BLOCK\n")
        self.assertEqual(rc1, 0)
        out1 = (self.tmp / "s1/1.txt").read_text(encoding="utf-8")
        self.assertIn("hello_world in_rb=1", out1)
        self.assertIn("[s1/1] END (exit 0)", out1)

        rc_dup = self.mod.cmd_normal("s1/1", "echo again\n")
        self.assertEqual(rc_dup, 2)
        rc_skip = self.mod.cmd_normal("s1/3", "echo step3\n")
        self.assertEqual(rc_skip, 2)

    def test_failed_execution_and_chained_fixes(self):
        rc = self.mod.cmd_normal("s1/1", "echo bad_cmd\nexit 3\n")
        self.assertEqual(rc, 3)
        fix1 = "text = text.replace('exit 3', 'exit 4')\n"
        self.assertEqual(self.mod.cmd_fix("s1/1", fix1), 4)
        self.assertEqual(self.mod.cmd_fix("s1/1", fix1), 2)
        fix2 = "text = text.replace('exit 4', 'echo fixed_ok')\n"
        self.assertEqual(self.mod.cmd_fix("s1/1_1", fix2), 0)
        out_f2 = (self.tmp / "s1/1_2.txt").read_text(encoding="utf-8")
        self.assertIn("fixed_ok", out_f2)

    def test_syntax_error_does_not_run(self):
        rc = self.mod.cmd_normal("s1/1", "if true; then\n")
        self.assertNotEqual(rc, 0)
        out = (self.tmp / "s1/1.txt").read_text(encoding="utf-8")
        self.assertIn("END (syntax error", out)

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
        src = SCRIPT.read_text(encoding="utf-8").replace(f'VERSION = "{cur_v}"', 'VERSION = "0.6.0"', 1)
        remote_file.write_text(src, encoding="utf-8")
        url = remote_file.as_uri()

        env = {**os.environ, "RUN_BLOCK_UPDATE_URL": url}
        r_chk = subprocess.run([str(installed), "--check-update"], capture_output=True, text=True, env=env, check=False)
        self.assertEqual(r_chk.returncode, 0)
        self.assertIn(f"{cur_v} -> 0.6.0", r_chk.stdout)

        r_up = subprocess.run([str(installed), "--update"], capture_output=True, text=True, env=env, check=False)
        self.assertEqual(r_up.returncode, 0)
        self.assertIn(f"updated {cur_v} -> 0.6.0", r_up.stdout)
        self.assertIn("## Terminal blocks (`my_block` v0.6.0)", r_up.stdout)

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
        self.assertIn("run_block s1/1 <<'RUN_BLOCK'", r1.stdout)

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
        self.assertIn("run_term_block s1/1 <<'RUN_BLOCK'", r2.stdout)


    def test_list_show_and_retry(self):
        self.mod.cmd_normal("s1/1", "echo first_step\n")
        r_list = subprocess.run([str(SCRIPT), "--list"], capture_output=True, text=True, check=False)
        self.assertEqual(r_list.returncode, 0)
        self.assertIn("s1/1", r_list.stdout)
        self.assertIn("END (exit 0)", r_list.stdout)

        r_show = subprocess.run([str(SCRIPT), "--show", "s1/1"], capture_output=True, text=True, check=False)
        self.assertEqual(r_show.returncode, 0)
        self.assertIn("echo first_step", r_show.stdout)

        r_retry = subprocess.run([str(SCRIPT), "--retry", "s1/1"], capture_output=True, text=True, check=False)
        self.assertEqual(r_retry.returncode, 0)
        self.assertIn("first_step", r_retry.stdout)

    def test_agent_install_create_and_update(self):
        target = self.tmp / "AGENTS.md"
        r1 = subprocess.run([str(SCRIPT), "--agents-install", str(target)], capture_output=True, text=True, check=False)
        self.assertEqual(r1.returncode, 0)
        self.assertTrue(target.is_file())
        c1 = target.read_text(encoding="utf-8")
        self.assertIn("<!-- run_block:start", c1)
        self.assertIn("<!-- run_block:end -->", c1)

        # Simulate an older version inside existing AGENTS.md with surrounding user content
        older = "# Project Rules\n\n" + c1.replace(f"v{self.mod.VERSION}", "v0.1.0") + "\n## Other Section\nKeep me.\n"
        target.write_text(older, encoding="utf-8")
        r2 = subprocess.run([str(SCRIPT), "--agents-install", str(target)], capture_output=True, text=True, check=False)
        self.assertEqual(r2.returncode, 0)
        c2 = target.read_text(encoding="utf-8")
        self.assertIn(f"v{self.mod.VERSION}", c2)
        self.assertNotIn("v0.1.0", c2)
        self.assertIn("# Project Rules", c2)
        self.assertIn("## Other Section\nKeep me.", c2)

if __name__ == "__main__":
    unittest.main()

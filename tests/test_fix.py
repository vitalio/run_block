"""Offline unit tests for src/fix.py."""

from __future__ import annotations

import contextlib
import io
import os
import shutil
import tempfile
import unittest
import unittest.mock
from pathlib import Path

try:
    from tests.helpers import INSTALL_SH, ROOT, SCRIPT, RunBlockTestCase, load_module
except ImportError:
    from helpers import INSTALL_SH, ROOT, SCRIPT, RunBlockTestCase, load_module  # type: ignore[no-redef]


class TestFix(RunBlockTestCase):
    def test_failed_execution_and_chained_fixes(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self.mod.cmd_normal("s1/1", "echo bad_cmd\nexit 3\n")
            self.assertEqual(rc, 3)
            # 1st failed fix on s1/1: rich AssertionError diagnostics in s1/1_1.txt
            bad_fix = "old_3 = 'missing'\nassert text.count(old_3) == 2\n"
            self.assertEqual(self.mod.cmd_fix("s1/1", bad_fix), 2)
            # 2nd fix targets s1/1_1 (which was NOT RUN and had no script): falls back to 1.sh,
            # allocates s1/1_2 without overwriting s1/1_1.txt, and fails with exit 4 (reaching limit=2)
            fix1 = "text = text.replace('exit 3', 'exit 4')\n"
            self.assertEqual(self.mod.cmd_fix("s1/1_1", fix1), 4)
            # Repeating --fix s1/1 hits the duplicate slot guard for s1/1_1 without allocating s1/1_3
            self.assertEqual(self.mod.cmd_fix("s1/1", fix1), 2)
            self.assertFalse((self.tmp / "s1/1_3").exists())
            self.assertIn(
                "NOT RUN: step already exists",
                (self.tmp / "s1/1_1/error").read_text(encoding="utf-8"),
            )
            # 3rd chained fix on s1/1_2 is rejected by the max-attempts loop guard in s1/1_3
            self.assertEqual(self.mod.cmd_fix("s1/1_2", fix1), 2)

            # On s1/2: test explicit chained fix (--fix s1/2_1 -> s1/2_2)
            self.assertEqual(self.mod.cmd_normal("s1/2", "echo bad2\nexit 3\n"), 3)
            self.assertEqual(self.mod.cmd_fix("s1/2", fix1), 4)
            fix2 = "assert text.count('exit 4') == 1\ntext = text.replace('exit 4', 'echo fixed_ok')\n"
            self.assertEqual(self.mod.cmd_fix("s1/2_1", fix2), 0)

        out_f1 = (self.tmp / "s1/1_1/out").read_text(encoding="utf-8")
        self.assertIn("at line 2: assert text.count(old_3) == 2 (actual: 0 == 2)", out_f1)
        out_f2 = (self.tmp / "s1/1_2/out").read_text(encoding="utf-8")
        self.assertIn("STOP --fix", out_f2)
        self.assertIn("s1/2", out_f2)
        out_f3 = (self.tmp / "s1/1_3/out").read_text(encoding="utf-8")
        self.assertIn("NOT RUN: STOP --fix", out_f3)
        self.assertIn("emit a fresh s1/2 block instead", out_f3)
        self.assertTrue((self.tmp / "s1/2_2/fix.py").is_file())
        self.assertTrue((self.tmp / "s1/2_2/block.sh").is_file())
        out_s2_f2 = (self.tmp / "s1/2_2/out").read_text(encoding="utf-8")
        self.assertIn("patched 2_1/block.sh -> 2_2/block.sh", out_s2_f2)
        self.assertIn("fixed_ok", out_s2_f2)

    def test_fix_anchor_diagnostic_hints(self):
        cases = [
            ("s1", "echo alpha\necho beta\n", "old = 'echo bata\\n'\nassert text.count(old) == 1\n",
             "Hint: closest match at line 2 (similarity"),
            ("s2", "echo a\necho b\n", "old = 'echo a\\n\\n'\nassert text.count(old) == 1\n",
             "Hint: anchor matches once without its trailing newline"),
            ("s3", "echo a\necho a\n", "old = 'echo a'\nassert text.count(old) == 1\n",
             "matches 2 times"),
            ("s4", "echo a\necho b\n", "text.replace('echo a', 'echo c')\n",
             "result of text.replace(...) is discarded"),
            ("s5", "echo a\necho b\n", "old = 'zzzzzzzzzzzz'\nassert text.count(old) == 1\n",
             "emit a fresh s5/2 block instead of --fix"),
            ("s6", "echo alpha\necho beta\n", "old = 'echo bata'\nassert old in text\n",
             "Hint: closest match at line 2 (similarity"),
            ("s7", "echo alpha\necho beta\n", "text = re.sub('echo bata', 'echo gamma', text)\n",
             "Hint: closest match at line 2 (similarity"),
        ]
        for session, script, fix, expected in cases:
            with self.subTest(session=session):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(self.mod.cmd_normal(f"{session}/1", script, auto_yes=True), 0)
                    self.assertEqual(self.mod.cmd_fix(f"{session}/1", fix, auto_yes=True), 2)
                out = (self.tmp / session / "1_1" / "out").read_text(encoding="utf-8")
                self.assertIn(expected, out)

    def test_fix_payload_shell_script_and_syntax_context(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.mod.cmd_normal("s1/1", "echo a\n", auto_yes=True), 0)
            self.assertEqual(self.mod.cmd_fix("s1/1", "git status -sb\necho hi\n", auto_yes=True), 2)
            self.assertEqual(self.mod.cmd_normal("s2/1", "echo a\n", auto_yes=True), 0)
            self.assertEqual(self.mod.cmd_fix("s2/1", "old = 'abc\nassert text.count(old) == 1\n", auto_yes=True), 2)
        out_shell = (self.tmp / "s1" / "1_1" / "out").read_text(encoding="utf-8")
        self.assertIn("looks like a shell script", out_shell)
        self.assertIn("fresh s1/2 block", out_shell)
        out_syn = (self.tmp / "s2" / "1_1" / "out").read_text(encoding="utf-8")
        self.assertIn("Context (line 1):", out_syn)
        self.assertIn(">   1 | old = 'abc", out_syn)
        self.assertIn("Hint: the RUN_FIX heredoc passes text literally", out_syn)

        # Shell commands that happen to be valid Python AST expressions (ls -la, cd /tmp, pwd, git)
        # and next_seq_ref when later steps already exist in session
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.mod.cmd_normal("s1/2", "echo step2\n", auto_yes=True), 0)
            for idx_cmd, sh_cmd in enumerate(("ls -la\n", "cd /tmp\n", "pwd\n", "git\n"), start=1):
                sess_sh = f"sh{idx_cmd}"
                self.assertEqual(self.mod.cmd_normal(f"{sess_sh}/1", "echo base\n", auto_yes=True), 0)
                self.assertEqual(self.mod.cmd_normal(f"{sess_sh}/2", "echo second\n", auto_yes=True), 0)
                self.assertEqual(self.mod.cmd_fix(f"{sess_sh}/1", sh_cmd, auto_yes=True), 2)
                sh_out = (self.tmp / sess_sh / "1_1" / "out").read_text(encoding="utf-8")
                self.assertIn("looks like a shell script", sh_out, sh_cmd)
                self.assertIn(f"fresh {sess_sh}/3 block", sh_out, sh_cmd)

    def test_fix_interactive_anchor_repair(self):
        class _Tty(io.StringIO):
            def isatty(self):
                return True

        script = "echo alpha one\necho beta two\n"
        fix = "old = 'echo beta twp\\n'\nnew = 'echo gamma\\n'\nassert text.count(old) == 1\ntext = text.replace(old, new, 1)\n"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.mod.cmd_normal("s1/1", script, auto_yes=True), 0)
            self.assertEqual(self.mod.cmd_normal("s2/1", script, auto_yes=True), 0)
        seen: list[str] = []

        def fake_run(label, script_path, *a, **kw):
            seen.append(Path(script_path).read_text(encoding="utf-8"))
            return 0

        with contextlib.redirect_stdout(_Tty()), \
                unittest.mock.patch.object(self.mod, "no_clipboard", return_value=False), \
                unittest.mock.patch.object(self.mod, "prompt_yes_no_box", return_value=True) as box, \
                unittest.mock.patch.object(self.mod, "run_script", side_effect=fake_run):
            rc = self.mod.cmd_fix("s1/1", fix)
        self.assertEqual(rc, 0)
        self.assertEqual(box.call_count, 1)
        self.assertEqual(seen, ["echo alpha one\necho gamma\n"])

        with contextlib.redirect_stdout(io.StringIO()), \
                unittest.mock.patch.object(self.mod, "prompt_yes_no_box", return_value=True) as box2:
            rc2 = self.mod.cmd_fix("s2/1", fix, auto_yes=True)
        self.assertEqual(rc2, 2)
        box2.assert_not_called()

        # Double quotes, triple quotes, and direct literal forms in _propose_anchor_repair
        for q_idx, q_fix in enumerate(
            (
                'old = "echo beta twp\\n"\nnew = "echo gamma\\n"\nassert old in text\ntext = text.replace(old, new, 1)\n',
                'old = """echo beta twp\n"""\nnew = """echo gamma\n"""\nassert text.count(old) == 1\ntext = text.replace(old, new, 1)\n',
                'assert "echo beta twp\\n" in text\ntext = text.replace("echo beta twp\\n", "echo gamma\\n", 1)\n',
            ),
            start=3,
        ):
            q_sess = f"s{q_idx}"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(self.mod.cmd_normal(f"{q_sess}/1", script, auto_yes=True), 0)
            q_seen: list[str] = []

            def fake_q_run(_lbl, sp, *_a, _dest=q_seen, **_kw):
                _dest.append(Path(sp).read_text(encoding="utf-8"))
                return 0

            with contextlib.redirect_stdout(_Tty()), \
                    unittest.mock.patch.object(self.mod, "no_clipboard", return_value=False), \
                    unittest.mock.patch.object(self.mod, "prompt_yes_no_box", return_value=True) as q_box, \
                    unittest.mock.patch.object(self.mod, "run_script", side_effect=fake_q_run):
                self.assertEqual(self.mod.cmd_fix(f"{q_sess}/1", q_fix), 0)
            self.assertEqual(q_box.call_count, 1)
            self.assertEqual(q_seen, ["echo alpha one\necho gamma\n"])

        # Declining anchor repair must NOT display a second NOT RUN box or offer_clipboard_copy,
        # and <step>/out and <step>/fix.py must already exist when prompt_yes_no_box runs.
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.mod.cmd_normal("s_dec/1", script, auto_yes=True), 0)
        artifact_state: dict[str, bool] = {}

        def check_artifacts_on_decline(*_a, **kw):
            op = kw.get("out_path")
            sp = kw.get("script_path")
            artifact_state["out_exists"] = bool(op and Path(op).is_file())
            artifact_state["fix_exists"] = bool(sp and Path(sp).is_file())
            return False

        tty_dec = _Tty()
        with contextlib.redirect_stdout(tty_dec), \
                unittest.mock.patch.object(self.mod, "no_clipboard", return_value=False), \
                unittest.mock.patch.object(self.mod, "prompt_yes_no_box", side_effect=check_artifacts_on_decline) as dec_box, \
                unittest.mock.patch.object(self.mod, "offer_clipboard_copy") as dec_clip:
            rc_dec = self.mod.cmd_fix("s_dec/1", fix)
        self.assertEqual(rc_dec, 2)
        self.assertEqual(dec_box.call_count, 1)
        dec_clip.assert_not_called()
        self.assertEqual(tty_dec.getvalue(), "")
        self.assertTrue(artifact_state.get("out_exists"))
        self.assertTrue(artifact_state.get("fix_exists"))

    def test_fix_anchor_found_in_referenced_repo_file(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "notes.txt").write_text("needle line\n", encoding="utf-8")
            script = "cat notes.txt\n"
            fn = self.mod._anchor_in_referenced_file
            self.assertEqual(fn("needle line", script, Path(td)), "notes.txt")
            self.assertIsNone(fn("absent text", script, Path(td)))
            self.assertIsNone(fn("needle line", "echo hi\n", Path(td)))
            self.assertIsNone(fn("needle line", script, None))
            fix = "assert text.count('needle line') == 1\n"
            hints = self.mod._fix_anchor_hints(fix, script, {"text": script}, "s1/2", Path(td))
            self.assertEqual(len(hints), 1)
            self.assertIn("exists in notes.txt", hints[0])
            self.assertIn("fresh s1/2 block", hints[0])

    def test_consecutive_failed_fixes_resets_on_ok_outcome(self):
        sdir = self.tmp / "s9"
        for stem, outcome, rc in (("1_1", "failed", 1), ("1_2", "ok", 0), ("1_3", "failed", 1)):
            step_d = sdir / stem
            step_d.mkdir(parents=True)
            self.mod.write_step_meta(step_d, duration_ms=5, exit_code=rc, outcome=outcome)
        self.assertEqual(self.mod._consecutive_failed_fixes(sdir, "1"), 1)

    def test_fix_collision_handling_and_repeated_reply_duplicate_guard(self):
        class _NoCloseStringIO(io.StringIO):
            def close(self) -> None:
                pass

        fake_stdout = io.StringIO()
        fake_stdout.isatty = lambda: True  # type: ignore[method-assign]

        sdir = self.tmp / "sfix"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.mod.cmd_normal("sfix/1", "echo broken_v0\nexit 3\n", auto_yes=True), 3)

        fix_v1 = "old = 'broken_v0'\nnew = 'fixed_v1'\nassert text.count(old) == 1\ntext = text.replace(old, new, 1)\ntext = text.replace('exit 3', 'exit 0')\n"
        fix_v2 = "old = 'broken_v0'\nnew = 'fixed_v2'\nassert text.count(old) == 1\ntext = text.replace(old, new, 1)\ntext = text.replace('exit 3', 'exit 0')\n"
        fix_v3 = "old = 'broken_v0'\nnew = 'fixed_v3'\nassert text.count(old) == 1\ntext = text.replace(old, new, 1)\ntext = text.replace('exit 3', 'exit 0')\n"

        # 1. Aborted fix slot (sfix/1_1) is automatically cleaned up and reused on repeated --fix sfix/1
        with unittest.mock.patch.object(self.mod, "confirm_execution", return_value=(False, "USER_ABORTED")), \
             contextlib.redirect_stdout(io.StringIO()):
            rc_aborted = self.mod.cmd_fix("sfix/1", fix_v1, auto_yes=False)
        self.assertEqual(rc_aborted, 130)
        self.assertTrue((sdir / "1_1" / "aborted").is_file())
        self.assertEqual(self.mod.read_step_meta(sdir / "1_1").get("outcome"), "aborted")

        with contextlib.redirect_stdout(io.StringIO()):
            rc_reused = self.mod.cmd_fix("sfix/1", fix_v1, auto_yes=True)
        self.assertEqual(rc_reused, 0)
        self.assertFalse((sdir / "1_1" / "aborted").exists())
        self.assertFalse((sdir / "1_2").exists())
        out_1_1 = (sdir / "1_1" / "out").read_text(encoding="utf-8")
        self.assertIn("fixed_v1", out_1_1)

        # 2. Non-interactive repeated --fix sfix/1 returns NOT RUN: step already exists without allocating 1_2
        buf_ni = io.StringIO()
        with contextlib.redirect_stdout(buf_ni):
            rc_ni_dup = self.mod.cmd_fix("sfix/1", fix_v2, auto_yes=True)
        self.assertEqual(rc_ni_dup, 2)
        self.assertFalse((sdir / "1_2").exists())
        self.assertEqual((sdir / "1_1" / "out").read_text(encoding="utf-8"), out_1_1)
        self.assertIn("NOT RUN: step already exists", (sdir / "1_1" / "error").read_text(encoding="utf-8"))

        # 3. Interactive STEP ALREADY EXISTS on --fix sfix/1:
        # 3a. Enter ('copy') copies existing 1_1/out to clipboard and returns 0
        tty_w_cp = _NoCloseStringIO()
        tty_r_cp = io.StringIO("\n")
        with unittest.mock.patch.object(self.mod, "no_clipboard", return_value=False), \
             unittest.mock.patch.object(self.mod, "clipboard_command", return_value=(["pbcopy"], "pbcopy < out")), \
             unittest.mock.patch.object(self.mod, "copy_file_to_clipboard", return_value=True) as mock_cp, \
             unittest.mock.patch.object(self.mod, "open_tty", return_value=(tty_w_cp, tty_r_cp)), \
             unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((100, 24))), \
             unittest.mock.patch.object(self.mod.sys, "stdout", fake_stdout):
            rc_cp = self.mod.cmd_fix("sfix/1", fix_v2, auto_yes=False)
        self.assertEqual(rc_cp, 0)
        mock_cp.assert_called_once_with(["pbcopy"], sdir / "1_1" / "out")
        self.assertFalse((sdir / "1_2").exists())

        # 3b. 'n' cancels with rc=2 without overwriting 1_1 or allocating 1_2
        tty_w_no = _NoCloseStringIO()
        tty_r_no = io.StringIO("n\n")
        with unittest.mock.patch.object(self.mod, "no_clipboard", return_value=False), \
             unittest.mock.patch.object(self.mod, "open_tty", return_value=(tty_w_no, tty_r_no)), \
             unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((100, 24))), \
             unittest.mock.patch.object(self.mod.sys, "stdout", fake_stdout):
            rc_no = self.mod.cmd_fix("sfix/1", fix_v2, auto_yes=False)
        self.assertEqual(rc_no, 2)
        self.assertFalse((sdir / "1_2").exists())

        # 3c. 'i' -> 'O' (overwrite) replaces sfix/1_1 in place without allocating 1_2
        tty_w_ov = _NoCloseStringIO()
        tty_r_ov = io.StringIO("i\nO\n")
        with unittest.mock.patch.object(self.mod, "no_clipboard", return_value=False), \
             unittest.mock.patch.object(self.mod, "clipboard_mode", return_value="never"), \
             unittest.mock.patch.object(self.mod, "open_tty", return_value=(tty_w_ov, tty_r_ov)), \
             unittest.mock.patch.object(self.mod, "confirm_execution", return_value=(True, None)), \
             unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((100, 24))), \
             unittest.mock.patch.object(self.mod.sys, "stdout", fake_stdout):
            rc_ov = self.mod.cmd_fix("sfix/1", fix_v2, auto_yes=False)
        self.assertEqual(rc_ov, 0)
        self.assertFalse((sdir / "1_2").exists())
        self.assertIn("✓ Overwriting sfix/1_1.", tty_w_ov.getvalue())
        self.assertIn("fixed_v2", (sdir / "1_1" / "out").read_text(encoding="utf-8"))

        # 3d. 'r' (renumber) on --fix sfix/1 renumbers sfix/1_1 -> sfix/1_2 and writes renumber Note in 1_2/out
        tty_w_rn = _NoCloseStringIO()
        tty_r_rn = io.StringIO("r\n")
        with unittest.mock.patch.object(self.mod, "no_clipboard", return_value=False), \
             unittest.mock.patch.object(self.mod, "clipboard_mode", return_value="never"), \
             unittest.mock.patch.object(self.mod, "open_tty", return_value=(tty_w_rn, tty_r_rn)), \
             unittest.mock.patch.object(self.mod, "confirm_execution", return_value=(True, None)), \
             unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((100, 24))), \
             unittest.mock.patch.object(self.mod.sys, "stdout", fake_stdout):
            rc_rn = self.mod.cmd_fix("sfix/1", fix_v3, auto_yes=False)
        self.assertEqual(rc_rn, 0)
        self.assertTrue((sdir / "1_2" / "block.sh").is_file())
        out_1_2 = (sdir / "1_2" / "out").read_text(encoding="utf-8")
        self.assertIn("[sfix/1_2] Note: renumbered from sfix/1_1 to sfix/1_2; continue from sfix/1_2.", out_1_2)
        self.assertIn("fixed_v3", out_1_2)
        self.assertEqual(self.mod.read_step_meta(sdir / "1_2").get("renumbered_from"), "sfix/1_1")

        # 4. Repeated run -rc (cmd_run_reply with from_clipboard=True) reuses aborted step and guards completed step/fix
        fence = chr(96) * 3
        reply_step2 = (
            "Running step 2 from clipboard.\n\n"
            + fence + "bash\n"
            "run sfix/2 <<'RUN_BLOCK'\n"
            "echo step2_from_rc\n"
            "RUN_BLOCK\n"
            + fence + "\n"
        )
        with unittest.mock.patch.object(self.mod, "clipboard_read_command", return_value=["wl-paste", "--no-newline"]), \
             unittest.mock.patch.object(self.mod, "read_clipboard_text", return_value=reply_step2):
            # First attempt aborted by user -> leaves sfix/2/aborted
            with unittest.mock.patch.object(self.mod, "confirm_execution", return_value=(False, "USER_ABORTED")), \
                 contextlib.redirect_stdout(io.StringIO()):
                rc_rc_abort = self.mod.cmd_run_reply(None, None, auto_yes=False, from_clipboard=True)
            self.assertEqual(rc_rc_abort, 130)
            self.assertTrue((sdir / "2" / "aborted").is_file())

            # Second attempt with same clipboard reply reuses sfix/2 (does NOT allocate sfix/3)
            with contextlib.redirect_stdout(io.StringIO()):
                rc_rc_ok = self.mod.cmd_run_reply(None, None, auto_yes=True, from_clipboard=True)
            self.assertEqual(rc_rc_ok, 0)
            self.assertFalse((sdir / "2" / "aborted").exists())
            self.assertFalse((sdir / "3").exists())
            self.assertIn("step2_from_rc", (sdir / "2" / "out").read_text(encoding="utf-8"))

            # Third attempt with same clipboard reply hits STEP ALREADY EXISTS on sfix/2 (does NOT allocate sfix/3)
            with contextlib.redirect_stdout(io.StringIO()):
                rc_rc_dup = self.mod.cmd_run_reply(None, None, auto_yes=True, from_clipboard=True)
            self.assertEqual(rc_rc_dup, 2)
            self.assertFalse((sdir / "3").exists())

    def test_fix_ast_validation_and_bundle_tamper_revert(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.mod.cmd_normal("s1/1", "echo safe_step_1\n")
        # 1. Unsafe --fix constructs must be rejected before exec()
        marker = self.tmp / "pwned.txt"
        for unsafe_fix in (
            f"import os\nos.system('touch {marker}')\n",
            f"__import__('os').system('touch {marker}')\n",
            "text = text.__class__.__name__\n",
            f"open('{marker}', 'w').write('x')\n",
        ):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = self.mod.cmd_fix("s1/1", unsafe_fix, auto_yes=True)
            self.assertEqual(rc, 2)
            self.assertIn("╭─ NOT RUN ", buf.getvalue())
            self.assertIn("Reason: unsafe construct in --fix", buf.getvalue())
            self.assertIn("NOT RUN: unsafe construct in --fix", (self.tmp / "s1/1_1/out").read_text(encoding="utf-8"))
            self.assertFalse(marker.exists())
            shutil.rmtree(self.tmp / "s1/1_1", ignore_errors=True)

        # 2. Tampering with 0 inside a running block must be automatically reverted
        bundle_file = self.tmp / "s1/0"
        orig_bundle = bundle_file.read_text(encoding="utf-8")
        buf2 = io.StringIO()
        with contextlib.redirect_stdout(buf2):
            rc2 = self.mod.cmd_normal(
                "s1/2",
                f"echo 'Sandbox: off' > {bundle_file}\n",
                auto_yes=True,
            )
        self.assertEqual(rc2, 0)
        self.assertEqual(bundle_file.read_text(encoding="utf-8"), orig_bundle)
        self.assertIn("SECURITY WARNING: block attempted to modify 0 (reverted)", buf2.getvalue())


if __name__ == "__main__":
    unittest.main()

"""Offline unit tests for src/inspect_cmd.py."""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import unittest
import unittest.mock

try:
    from tests.helpers import INSTALL_SH, ROOT, SCRIPT, RunBlockTestCase, load_module
except ImportError:
    from helpers import INSTALL_SH, ROOT, SCRIPT, RunBlockTestCase, load_module  # type: ignore[no-redef]


class TestInspectCmd(RunBlockTestCase):
    def test_done_stats_card_and_list_badge(self):
        self._assert_ok(
            self._run(
                ["--start", "--session", "s1"],
                input="Role: work\nTask: F94\nTitle: Clean end session card\n\nprompt\n",
            )
        )
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.mod.cmd_normal("s1/1", "echo one\n"), 0)
            self.assertNotEqual(self.mod.cmd_normal("s1/2", "exit 3\n"), 0)
        meta_path = self.tmp / "s1" / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        self.assertEqual(
            (meta["stats"]["steps"], meta["stats"]["ok"], meta["stats"]["failed"]), (2, 1, 1)
        )
        self.assertNotIn("completed", meta)
        meta["stats"]["started_at"] = "2026-11-23T19:00:00Z"
        meta["stats"]["duration_ms"] = 80000
        meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

        with unittest.mock.patch.object(self.mod, "_utc_now_iso", return_value="2026-11-23T19:25:01Z"):
            buf_done = io.StringIO()
            with contextlib.redirect_stdout(buf_done):
                self.assertEqual(self.mod.cmd_done("s1", note="wrap up"), 0)
        done_out = buf_done.getvalue()
        self.assertIn("╭─ END SESSION ", done_out)
        self.assertRegex(done_out, r"Session:\s+s1")
        self.assertRegex(done_out, r"Workdir:\s+")
        self.assertRegex(done_out, r"Role:\s+work")
        self.assertRegex(done_out, r"Task:\s+F94")
        self.assertRegex(done_out, r"Title:\s+Clean end session card")
        self.assertIn("\n│\n", done_out)
        self.assertRegex(done_out, r"Steps:\s+2 \(1 ok, 1 failed\)")
        self.assertNotIn("Results:", done_out)
        self.assertNotIn("--fix", done_out)
        self.assertRegex(done_out, r"Duration:\s+25m 1s \(1m 20s exec\)")
        self.assertRegex(done_out, r"Started:\s+2026-11-23T19:00:00Z")
        self.assertRegex(done_out, r"Completed:\s+2026-11-23T19:25:01Z")
        self.assertLess(done_out.index("Started:"), done_out.index("Completed:"))
        self.assertLess(done_out.index("Completed:"), done_out.index("Note:"))
        self.assertRegex(done_out, r"Note:\s+wrap up")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        self.assertIs(meta["completed"], True)
        self.assertEqual(meta["completed_note"], "wrap up")

        # Direct unit checks for _session_stats_lines modifiers and duration fallback
        stats_lines_mod = self.mod._session_stats_lines({
            "completed_at": "2026-11-23T19:00:00Z",
            "completed_note": "all good",
            "stats": {
                "steps": 21,
                "ok": 11,
                "failed": 10,
                "fix": 2,
                "renumbered": 0,
                "duration_ms": 15000,
                "started_at": "2026-11-23T19:00:00Z",
            },
        })
        self.assertEqual(
            stats_lines_mod,
            [
                "Steps: 21 (11 ok, 10 failed · 2 fix)",
                "Duration: 15.0s",
                "Started: 2026-11-23T19:00:00Z",
                "Completed: 2026-11-23T19:00:00Z",
                "Note: all good",
            ],
        )
        stats_lines_ok = self.mod._session_stats_lines({
            "stats": {"steps": 15, "ok": 15, "failed": 0, "fix": 0, "renumbered": 0, "duration_ms": 500},
        })
        self.assertEqual(stats_lines_ok, ["Steps: 15 (15 ok)", "Duration: 500ms"])

        r_list = self._run([str(SCRIPT), "--list"])
        self._assert_ok(r_list)
        self.assertRegex(r_list.stdout, r"s1 .*last: s1/2 .*\[DONE\]")
        r_blocks = self._run([str(SCRIPT), "--list", "s1"])
        self._assert_ok(r_blocks)
        self.assertIn("[DONE]:", r_blocks.stdout)
        r_again = self._run([str(SCRIPT), "--done", "s1"])
        self._assert_ok(r_again)
        self.assertIn("already marked as completed", r_again.stdout)

        self._assert_ok(
            self._run(
                ["--start", "--session", "s2"],
                input="Role: work\nTask: F94\n\nprompt2\n",
            )
        )
        r_latest = self._run([str(SCRIPT), "--done", "-y", "-m", "headless note"])
        self._assert_ok(r_latest)
        self.assertIn("[s2] END SESSION\n", r_latest.stdout)
        self.assertNotRegex(r_latest.stdout, r"(?m)^Session:")
        self.assertNotIn("\n\n", r_latest.stdout)
        self.assertRegex(r_latest.stdout, r"Workdir:\s+")
        self.assertRegex(r_latest.stdout, r"Role:\s+work")
        self.assertRegex(r_latest.stdout, r"Task:\s+F94")
        self.assertRegex(r_latest.stdout, r"Steps:\s+0")
        self.assertRegex(r_latest.stdout, r"Note:\s+headless note")

    def test_completed_session_blocks_runs_until_reopened(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.mod.cmd_normal("s1/1", "echo one\n"), 0)
            self.assertEqual(self.mod.cmd_done("s1"), 0)
        sdir = self.tmp / "s1"
        fix_code = "old = 'echo one'\nnew = 'echo fixed'\nassert text.count(old) == 1\ntext = text.replace(old, new, 1)\n"
        cases = (
            ("run", lambda: self.mod.cmd_normal("s1/2", "echo two\n"), "2"),
            ("fix", lambda: self.mod.cmd_fix("s1/1", fix_code), "1_1"),
            ("retry", lambda: self.mod.cmd_retry("s1/1"), None),
        )
        for kind, call, absent in cases:
            with self.subTest(kind=kind):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc = call()
                self.assertEqual(rc, 2, msg=buf.getvalue())
                self.assertIn("marked as completed", re.sub(r"[│\s]+", " ", buf.getvalue()))
                self.assertTrue(self.mod.is_session_completed(sdir))
                if absent is not None:
                    self.assertFalse(self.mod._step_dir(sdir, absent).exists())

        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.mod.cmd_normal("s1/2", "echo two\n", auto_yes=True), 0)
        self.assertFalse(self.mod.is_session_completed(sdir))
        meta = self.mod.read_session_meta(sdir)
        self.assertEqual(meta["stats"]["steps"], 2)
        self.assertNotIn("completed_at", meta["stats"])

        with contextlib.redirect_stdout(io.StringIO()):
            self.mod.cmd_done("s1")
        os.environ["RUN_BLOCK_HEADLESS"] = "1"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.mod.cmd_retry("s1/2"), 0)
        self.assertFalse(self.mod.is_session_completed(sdir))

    def test_completed_session_interactive_confirmation(self):
        class _Tty(io.StringIO):
            def isatty(self):
                return True

        self._assert_ok(
            self._run(
                ["--start", "--session", "s1"],
                input="Role: work\nTask: F94\nTitle: Guard completed session\n\nprompt\n",
            )
        )
        with contextlib.redirect_stdout(io.StringIO()):
            self.mod.cmd_normal("s1/1", "echo one\n")
            self.mod.cmd_done("s1", note="done for today")
        sdir = self.tmp / "s1"
        with unittest.mock.patch.object(self.mod, "prompt_yes_no_box", return_value=False) as box, \
                unittest.mock.patch.object(self.mod, "offer_clipboard_copy"), \
                contextlib.redirect_stdout(_Tty()):
            rc = self.mod.cmd_normal("s1/2", "echo two\n")
        self.assertEqual(rc, 130)
        box.assert_called_once()
        args, kwargs = box.call_args
        self.assertEqual(args[0], "SESSION COMPLETED")
        self.assertEqual(args[2], "-> Reopen session s1?")
        self.assertFalse(kwargs["default_yes"])
        box_lines = args[1]
        self.assertIn("", box_lines)
        sep_idx = box_lines.index("")
        hdr_part = "\n".join(box_lines[:sep_idx])
        body_part = "\n".join(box_lines[sep_idx + 1 :])
        self.assertRegex(hdr_part, r"Step:\s+s1/2")
        self.assertRegex(hdr_part, r"Workdir:\s+")
        self.assertRegex(hdr_part, r"Role:\s+work")
        self.assertRegex(hdr_part, r"Task:\s+F94")
        self.assertRegex(hdr_part, r"Title:\s+Guard completed session")
        self.assertRegex(body_part, r"Completed:\s+")
        self.assertRegex(body_part, r"Note:\s+done for today")
        self.assertTrue(self.mod.is_session_completed(sdir))
        self.assertFalse(self.mod._step_dir(sdir, "2").exists())

        with unittest.mock.patch.object(self.mod, "prompt_yes_no_box", return_value=True), \
                unittest.mock.patch.object(self.mod, "run_script", return_value=0) as run, \
                contextlib.redirect_stdout(_Tty()):
            rc = self.mod.cmd_normal("s1/2", "echo two\n")
        self.assertEqual(rc, 0)
        run.assert_called_once()
        self.assertFalse(self.mod.is_session_completed(sdir))

    def test_list_show_and_retry(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.mod.cmd_normal("s1/1", "echo first_step\n")
        r_list = self._run([str(SCRIPT), "--list"], capture_output=True, text=True, check=False)
        self.assertEqual(r_list.returncode, 0)
        self.assertIn("s1/1", r_list.stdout)
        self.assertRegex(r_list.stdout, r"ok \([^)\n]+\)")

        r_show = self._run([str(SCRIPT), "--show", "s1/1"], capture_output=True, text=True, check=False)
        self.assertEqual(r_show.returncode, 0)
        self.assertIn("echo first_step", r_show.stdout)

        r_retry = self._run([str(SCRIPT), "--retry", "s1/1"], capture_output=True, text=True, check=False)
        self.assertEqual(r_retry.returncode, 0)
        self.assertIn("first_step", r_retry.stdout)

    def test_session_lifecycle_state_and_step_outcome_meta(self):
        sdir = self.tmp / "s7"
        self.assertEqual(self.mod.get_session_state(sdir), "empty")
        with contextlib.redirect_stdout(io.StringIO()):
            self.mod.start_session("s7")
        self.assertEqual(self.mod.get_session_state(sdir), "bundle-only")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.mod.cmd_normal("s7/1", "echo one\n"), 0)
            self.assertNotEqual(self.mod.cmd_normal("s7/2", "exit 3\n"), 0)
            rc_syn = self.mod.cmd_normal("s7/3", "if then\n")
        self.assertNotEqual(rc_syn, 0)
        self.assertEqual(self.mod.get_session_state(sdir), "active")
        expected = (("1", "ok", 0), ("2", "failed", 3), ("3", "syntax-error", rc_syn))
        for stem, outcome, rc in expected:
            with self.subTest(step=stem):
                meta = self.mod.read_step_meta(sdir / stem)
                self.assertEqual(meta.get("outcome"), outcome)
                self.assertEqual(meta.get("exit_code"), rc)
        self.assertRegex(self.mod._step_status(sdir, "1"), r"^ok \(\S+\)$")
        self.assertRegex(self.mod._step_status(sdir, "2"), r"^exit 3 \(\S+\)$")
        self.assertEqual(self.mod._step_status(sdir, "3"), f"syntax-error (exit {rc_syn})")
        self.mod.set_session_completed(sdir)
        self.assertEqual(self.mod.get_session_state(sdir), "done")

    def test_step_outcome_legacy_artifact_fallback(self):
        sdir = self.tmp / "s8"
        legacy = {
            "1": ("out", "[s8/1] START\n\n[s8/1] END (1.5s)\n", "ok", "ok (1.5s)"),
            "2": ("out", "[s8/2] END (exit 2, 1.0s)\n", "failed", "exit 2 (1.0s)"),
            "3": ("out", "[s8/3] END (syntax error, exit 2)\n", "syntax-error", "syntax-error (exit 2)"),
            "4": ("error", "[s8/4] NOT RUN: empty script on stdin\n", "not-run", "not-run"),
            "5": ("aborted", "aborted\n", "aborted", "aborted"),
            "6": ("block.sh", "echo 6\n", "saved", "saved"),
        }
        for stem, (fname, text, _outcome, _status) in legacy.items():
            (sdir / stem).mkdir(parents=True)
            (sdir / stem / fname).write_text(text, encoding="utf-8")
        for stem, (_fname, _text, outcome, status) in legacy.items():
            with self.subTest(step=stem):
                self.assertEqual(self.mod._step_outcome(sdir, stem)["outcome"], outcome)
                self.assertEqual(self.mod._step_status(sdir, stem), status)
        self.assertEqual([d.name for d in self.mod._iter_session_steps(sdir)], list(legacy))
        self.assertEqual(self.mod._step_outcome(sdir, "4")["reason"], "empty script on stdin")

    def test_list_open_session_next_hint_and_not_run_rows(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.mod.cmd_normal("s1/1", "echo one\n"), 0)
        r_list = self._run([str(SCRIPT), "--list"])
        self._assert_ok(r_list)
        self.assertRegex(r_list.stdout, r"s1 .*last: s1/1 \(ok \([^)\n]+\)\)\s+next: s1/2")
        self.assertNotIn("[DONE]", r_list.stdout)
        r_blocks = self._run([str(SCRIPT), "--list", "s1"])
        self._assert_ok(r_blocks)
        self.assertIn("next: s1/2", r_blocks.stdout)
        step_fix = self.tmp / "s1" / "1_1"
        step_fix.mkdir()
        self.mod.write_step_meta(
            step_fix, duration_ms=0, exit_code=2, outcome="not-run",
            reason="STOP --fix: guard", fix_target="s1/1",
        )
        r_fix = self._run([str(SCRIPT), "--list", "s1"])
        self._assert_ok(r_fix)
        self.assertRegex(r_fix.stdout, r"s1/1_1\s+not-run\s+Reason: STOP --fix: guard; --fix s1/1")

    def test_list_filter_and_session_context_columns(self):
        for name, task in (("s1", "F20"), ("s2", "F21")):
            self._assert_ok(
                self._run(["--start", "--session", name], input=f"Role: work\nTask: {task}\n\nbody\n")
            )
        r_all = self._run(["--list"])
        self._assert_ok(r_all)
        self.assertRegex(r_all.stdout, r"Workdir: .*  Role: work  Task: F20")
        self.assertRegex(r_all.stdout, r"\d{4}-\d\d-\d\d \d\d:\d\d UTC")
        r_task = self._run(["--list", "--filter", "f21"])
        self._assert_ok(r_task)
        self.assertIn("Task: F21", r_task.stdout)
        self.assertNotIn("Task: F20", r_task.stdout)
        workdir = self.mod.parse_bundle_headers(self.tmp / "s1").get("workdir", "")
        self.assertTrue(workdir)
        r_wd = self._run(["--list", "--filter", workdir])
        self._assert_ok(r_wd)
        self.assertIn("Task: F20", r_wd.stdout)
        r_none = self._run(["--list", "--filter", "no-such-text"])
        self._assert_ok(r_none)
        self.assertIn("No sessions matching 'no-such-text'", r_none.stdout)
        for argv in (["--list", "--filter"], ["--list", "s1", "--filter", "x"], ["--list", "s1", "s2"]):
            with self.subTest(argv=argv):
                self.assertNotEqual(self._run(argv).returncode, 0)

    def test_info_show_session_forms_and_retry_session(self):
        self._assert_ok(
            self._run(["--start", "--session", "s1"], input="Role: work\nTask: F20\n\nbody\n")
        )
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.mod.cmd_normal("s1/1", "echo first_step\n"), 0)
            self.assertEqual(self.mod.cmd_normal("s1/2", "echo second_step\n"), 0)
        r_show = self._run(["--show", "s1"])
        self._assert_ok(r_show)
        for needle in (
            "Session: s1", f"Path: {self.tmp / 's1'}", "State: active", "Next: s1/3",
            "Task: F20", "Role: work", "s1/0", "s1/1", "s1/2",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, r_show.stdout)

        r_script = self._run(["--show", "s1/2", "--script"])
        self._assert_ok(r_script)
        self.assertIn("echo second_step", r_script.stdout)
        self.assertNotIn("=== [", r_script.stdout)
        r_out = self._run(["--show", "s1/2", "--out"])
        self._assert_ok(r_out)
        self.assertIn("second_step", r_out.stdout)
        self.assertIn("[s1/2] END", r_out.stdout)
        self.assertNotIn("=== [s1/2] Script", r_out.stdout)
        r_sess_out = self._run(["--show", "s1", "--out"])
        self._assert_ok(r_sess_out)
        self.assertIn("second_step", r_sess_out.stdout)
        for argv in (["--show", "s1/0", "--script"], ["--show", "s1/2", "--script", "--out"],
                     ["--show", "s1/2", "--out", "--part", "1"], ["--show", "s1", "s2"],
                     ["--info"], ["--info", "s1"]):
            with self.subTest(argv=argv):
                self.assertNotEqual(self._run(argv).returncode, 0)

        r_retry = self._run(["--retry", "s1"])
        self._assert_ok(r_retry)
        self.assertIn("second_step", r_retry.stdout)
        self.assertNotIn("first_step", r_retry.stdout)
        self.assertNotEqual(self._run(["--retry", "no-such-session"]).returncode, 0)


if __name__ == "__main__":
    unittest.main()

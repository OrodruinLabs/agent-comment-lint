"""The per-session snapshot files: written once, read back, and cleaned up after a week."""
import os
import shutil
import tempfile
import time
import unittest

from agent_comment_lint import session

ID = "a" * 40
ID2 = "b" * 40


class TestSessionFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.directory = os.path.join(self.tmp, "sessions")

    def test_a_snapshot_is_recorded_once_and_read_back(self):
        session.record(self.directory, "s1", ID)
        session.record(self.directory, "s1", ID2)
        self.assertEqual(session.recorded(self.directory, "s1"), ID)

    def test_an_unknown_session_has_no_snapshot(self):
        session.record(self.directory, "s1", ID)
        self.assertIsNone(session.recorded(self.directory, "nope"))

    def test_snapshots_older_than_seven_days_are_removed(self):
        os.makedirs(self.directory)
        old = os.path.join(self.directory, "old")
        with open(old, "w", encoding="ascii") as handle:
            handle.write(ID)
        eight_days_ago = time.time() - 8 * 24 * 3600
        os.utime(old, (eight_days_ago, eight_days_ago))
        session.record(self.directory, "s2", ID)
        self.assertFalse(os.path.exists(old))
        self.assertEqual(session.recorded(self.directory, "s2"), ID)

    def test_a_missing_directory_is_created(self):
        self.assertFalse(os.path.exists(self.directory))
        session.record(self.directory, "s1", ID)
        self.assertTrue(os.path.isdir(self.directory))

    def test_a_missing_directory_has_no_snapshot(self):
        self.assertIsNone(session.recorded(self.directory, "s1"))

    def test_only_a_full_object_id_is_read_back(self):
        os.makedirs(self.directory)
        for text, expected in (("--output=x", None), ("abc123", None), (ID, ID), ("c" * 64, "c" * 64),
                               (ID + "\n", ID)):
            with open(os.path.join(self.directory, "s"), "w", encoding="ascii") as handle:
                handle.write(text)
            self.assertEqual(session.recorded(self.directory, "s"), expected, text)

    def test_the_id_patterns_match_whole_strings_only(self):
        self.assertIsNone(session.SESSION_ID.match("abc\n"))
        self.assertIsNone(session.OBJECT_ID.match(ID + "\n"))
        self.assertTrue(session.SESSION_ID.match("abc") and session.OBJECT_ID.match(ID))

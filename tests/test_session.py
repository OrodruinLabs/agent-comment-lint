"""The per-session snapshot files: written once, read back, and cleaned up after a week."""
import os
import shutil
import tempfile
import time
import unittest

from agent_comment_lint import session


class TestSessionFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.directory = os.path.join(self.tmp, "sessions")

    def test_a_snapshot_is_recorded_once_and_read_back(self):
        session.record(self.directory, "s1", "t1")
        session.record(self.directory, "s1", "t2")
        self.assertEqual(session.recorded(self.directory, "s1"), "t1")

    def test_an_unknown_session_has_no_snapshot(self):
        session.record(self.directory, "s1", "t1")
        self.assertIsNone(session.recorded(self.directory, "nope"))

    def test_snapshots_older_than_seven_days_are_removed(self):
        os.makedirs(self.directory)
        old = os.path.join(self.directory, "old")
        with open(old, "w", encoding="ascii") as handle:
            handle.write("t")
        eight_days_ago = time.time() - 8 * 24 * 3600
        os.utime(old, (eight_days_ago, eight_days_ago))
        session.record(self.directory, "s2", "t")
        self.assertFalse(os.path.exists(old))
        self.assertEqual(session.recorded(self.directory, "s2"), "t")

    def test_a_missing_directory_is_created(self):
        self.assertFalse(os.path.exists(self.directory))
        session.record(self.directory, "s1", "t1")
        self.assertTrue(os.path.isdir(self.directory))

    def test_a_missing_directory_has_no_snapshot(self):
        self.assertIsNone(session.recorded(self.directory, "s1"))

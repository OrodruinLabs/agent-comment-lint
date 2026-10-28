"""Reading git's answers: a record that is not shaped as asked is a git failure, never a traceback."""
import unittest

from unittest import mock

from agent_comment_lint import gitio


class TestChangedFiles(unittest.TestCase):
    SAME = "0" * 39 + "1"
    OTHER = "0" * 39 + "2"

    def changes(self, output):
        with mock.patch.object(gitio, "_git", return_value=output):
            return gitio.changed_files(".", "a...b")

    def raw(self, status, *paths, same=True):
        return ":100644 100755 %s %s %s\0" % (self.SAME, self.SAME if same else self.OTHER, status) + \
            "".join(path + "\0" for path in paths)

    def test_plain_binary_and_renamed_records(self):
        output = (self.raw("M", "a.cs", same=False) + self.raw("M", "b.png", same=False)
                  + self.raw("R100", "old name.cs", "new name.cs")
                  + "3\t1\ta.cs\0-\t-\tb.png\x000\t0\t\0old name.cs\0new name.cs\0")
        self.assertEqual(self.changes(output), {"a.cs": (3, False), "b.png": (None, False), "new name.cs": (0, True)})

    def test_a_mode_change_and_a_pure_rename_keep_their_content(self):
        output = (self.raw("M", "a.ts") + self.raw("R100", "old.ts", "new.ts") + self.raw("M", "b.ts", same=False)
                  + self.raw("R090", "c.ts", "d.ts", same=False)
                  + "-\t-\ta.ts\0-\t-\t\0old.ts\0new.ts\0-\t-\tb.ts\0-\t-\t\0c.ts\0d.ts\0")
        self.assertEqual(self.changes(output), {"a.ts": (None, True), "new.ts": (None, True),
                                                "b.ts": (None, False), "d.ts": (None, False)})

    def test_no_output_is_no_changed_path(self):
        self.assertEqual(self.changes(""), {})

    def test_a_record_that_is_not_shaped_as_asked_is_a_git_failure_that_names_its_kind(self):
        numstat = ("3\t1", "three\t1\ta.cs\0", "1\t0\t\0", "1\t0\t\0old.cs")
        raw = (":100644 100755 %s M\0a.ts\0" % self.SAME, self.raw("R100", "old.ts")[:-1], ":100644 100755\0")
        for kind, cut in (("--numstat", numstat), ("--raw", raw)):
            for output in cut:
                with self.assertRaises(gitio.GitError, msg=output) as caught:
                    self.changes(output)
                self.assertTrue(str(caught.exception).startswith("git diff %s printed a record" % kind), output)

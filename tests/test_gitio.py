"""Reading git's answers: a record that is not shaped as asked is a git failure, never a traceback."""
import os
import shutil
import subprocess
import tempfile
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


class TestRepository(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "Test")

    def git(self, *args):
        return subprocess.run(["git"] + list(args), cwd=self.tmp, capture_output=True, text=True, check=True).stdout

    def write(self, name, text):
        with open(os.path.join(self.tmp, name), "wb") as handle:
            handle.write(text)

    def commit(self):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "c")

    def test_a_snapshot_holds_tracked_and_untracked_paths_as_they_are_on_disk(self):
        self.write("a.ts", b"one\n")
        self.commit()
        self.write("a.ts", b"one\ntwo\n")
        self.write("b.ts", b"new\n")
        tree = gitio.snapshot_tree(self.tmp, ["a.ts", "b.ts"])
        self.assertEqual(gitio.blob(self.tmp, tree + ":a.ts"), b"one\ntwo\n")
        self.assertEqual(gitio.blob(self.tmp, tree + ":b.ts"), b"new\n")

    def test_a_snapshot_leaves_the_real_index_untouched(self):
        self.write("a.ts", b"one\n")
        self.commit()
        self.write("b.ts", b"new\n")
        self.git("add", "b.ts")
        before = self.git("diff", "--cached", "--name-only")
        gitio.snapshot_tree(self.tmp, ["a.ts", "b.ts", "c.ts"])
        self.assertEqual(self.git("diff", "--cached", "--name-only"), before)

    def test_a_snapshot_works_before_the_first_commit(self):
        self.write("a.ts", b"one\n")
        tree = gitio.snapshot_tree(self.tmp, ["a.ts"])
        self.assertEqual(gitio.blob(self.tmp, tree + ":a.ts"), b"one\n")

    def test_a_deleted_tracked_path_is_absent_from_the_snapshot(self):
        self.write("a.ts", b"one\n")
        self.commit()
        os.remove(os.path.join(self.tmp, "a.ts"))
        tree = gitio.snapshot_tree(self.tmp, ["a.ts"])
        self.assertEqual(self.git("ls-tree", tree, "--", "a.ts"), "")

    def test_two_trees_diff_as_a_span(self):
        self.write("a.ts", b"one\n")
        old = gitio.snapshot_tree(self.tmp, ["a.ts"])
        self.write("a.ts", b"one\ntwo\n")
        new = gitio.snapshot_tree(self.tmp, ["a.ts"])
        self.assertEqual(gitio.changed_files(self.tmp, (old, new))["a.ts"].added, 1)

    def test_committed_blob_is_none_for_a_path_head_lacks(self):
        self.write("a.ts", b"one\n")
        self.commit()
        self.assertEqual(gitio.committed_blob(self.tmp, "a.ts"), b"one\n")
        self.assertIsNone(gitio.committed_blob(self.tmp, "missing.ts"))

    def test_has_head_is_false_before_the_first_commit(self):
        self.assertFalse(gitio.has_head(self.tmp))
        self.write("a.ts", b"one\n")
        self.commit()
        self.assertTrue(gitio.has_head(self.tmp))

    def test_git_path_is_absolute(self):
        path = gitio.git_path(self.tmp, "index")
        self.assertTrue(os.path.isabs(path))
        self.assertEqual(os.path.basename(path), "index")

    def subdirectory(self):
        self.write("a.ts", b"top\n")
        os.mkdir(os.path.join(self.tmp, "sub"))
        self.write("sub/a.ts", b"sub\n")
        self.commit()
        return os.path.join(self.tmp, "sub")

    def test_committed_blob_reads_the_path_under_a_subdirectory_root(self):
        sub = self.subdirectory()
        self.assertEqual(gitio.committed_blob(sub, "a.ts"), b"sub\n")

    def test_a_snapshot_taken_in_a_subdirectory_holds_the_files_under_that_root(self):
        sub = self.subdirectory()
        self.write("sub/a.ts", b"changed\n")
        tree = gitio.snapshot_tree(sub, ["a.ts"])
        self.assertEqual(gitio.blob(sub, tree + ":./a.ts"), b"changed\n")

    def test_a_temporary_index_that_cannot_be_made_is_a_git_error(self):
        self.write("a.ts", b"one\n")
        self.commit()
        with mock.patch.object(shutil, "copyfile", side_effect=OSError(28, "No space left on device")):
            with self.assertRaises(gitio.GitError):
                gitio.snapshot_tree(self.tmp, ["a.ts"])

    def test_has_head_raises_outside_any_repository(self):
        outside = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        with mock.patch.dict(os.environ, {"GIT_CEILING_DIRECTORIES": os.path.dirname(outside)}):
            with self.assertRaises(gitio.GitError):
                gitio.has_head(outside)

    def test_an_empty_snapshot_is_still_a_tree(self):
        self.write("a.ts", b"one\n")
        self.commit()
        tree = gitio.snapshot_tree(self.tmp, [])
        self.assertEqual(gitio.blob(self.tmp, tree + ":a.ts"), b"one\n")

    def test_a_path_with_a_space_survives_the_snapshot(self):
        self.write("my file.ts", b"one\n")
        tree = gitio.snapshot_tree(self.tmp, ["my file.ts"])
        self.assertEqual(gitio.blob(self.tmp, tree + ":my file.ts"), b"one\n")

    def test_a_blob_that_does_not_exist_is_a_git_error(self):
        self.write("a.ts", b"one\n")
        self.commit()
        with self.assertRaises(gitio.GitError):
            gitio.blob(self.tmp, "HEAD:./missing.ts")

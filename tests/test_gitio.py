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
        self.assertEqual(self.changes(output), {"a.cs": (3, False, self.OTHER), "b.png": (None, False, self.OTHER),
                                                "new name.cs": (0, True, self.SAME)})

    def test_a_mode_change_and_a_pure_rename_keep_their_content(self):
        output = (self.raw("M", "a.ts") + self.raw("R100", "old.ts", "new.ts") + self.raw("M", "b.ts", same=False)
                  + self.raw("R090", "c.ts", "d.ts", same=False)
                  + "-\t-\ta.ts\0-\t-\t\0old.ts\0new.ts\0-\t-\tb.ts\0-\t-\t\0c.ts\0d.ts\0")
        self.assertEqual(self.changes(output), {"a.ts": (None, True, self.SAME), "new.ts": (None, True, self.SAME),
                                                "b.ts": (None, False, self.OTHER), "d.ts": (None, False, self.OTHER)})

    def test_no_output_is_no_changed_path(self):
        self.assertEqual(self.changes(""), {})

    def test_a_count_with_no_record_of_its_blobs_is_a_git_failure(self):
        with self.assertRaises(gitio.GitError) as caught:
            self.changes(self.raw("M", "a.cs", same=False) + "3\t1\ta.cs\x001\t0\tb.cs\0")
        self.assertTrue(str(caught.exception).startswith("git diff --raw printed a record"))

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

    def commit_both(self, text):
        self.write("a.md", text)
        self.write("b.ts", text)
        self.commit()

    def conflicted(self):
        """A merge stopped on conflicts in `a.md` and `b.ts`, with the working tree's `b.ts` then resolved."""
        os.mkdir(os.path.join(self.tmp, "sub"))
        self.write("sub/c.ts", b"const c = 1;\n")
        self.commit_both(b"base\n")
        self.git("checkout", "-q", "-b", "other")
        self.commit_both(b"other\n")
        self.git("checkout", "-q", "-")
        self.commit_both(b"mine\n")
        subprocess.run(["git", "merge", "-q", "other"], cwd=self.tmp, capture_output=True)
        self.write("b.ts", b"resolved\n")
        self.assertIn("a.md", self.git("ls-files", "-u"))

    def test_a_snapshot_mid_merge_takes_covered_paths_from_disk_and_leaves_the_real_index_alone(self):
        self.conflicted()
        tree = gitio.snapshot_tree(self.tmp, ["b.ts"])
        self.assertEqual(gitio.blob(self.tmp, tree + ":b.ts"), b"resolved\n")
        self.assertIn("a.md", self.git("ls-files", "-u"))

    def test_a_snapshot_in_a_subdirectory_mid_merge_is_not_stopped_by_conflicts_above_it(self):
        self.conflicted()
        sub = os.path.join(self.tmp, "sub")
        self.write("sub/c.ts", b"const c = 2;\n")
        tree = gitio.snapshot_tree(sub, ["c.ts"])
        self.assertEqual(gitio.blob(sub, tree + ":./c.ts"), b"const c = 2;\n")

    def test_has_object_is_false_only_for_an_object_the_repository_lacks(self):
        self.write("a.ts", b"one\n")
        self.assertTrue(gitio.has_object(self.tmp, gitio.snapshot_tree(self.tmp, ["a.ts"])))
        self.assertFalse(gitio.has_object(self.tmp, "0" * 39 + "1"))
        outside = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        with mock.patch.dict(os.environ, {"GIT_CEILING_DIRECTORIES": os.path.dirname(outside)}):
            with self.assertRaises(gitio.GitError):
                gitio.has_object(outside, "0" * 39 + "1")

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

    def blob_id(self, text):
        self.write("x.bin", text)
        return self.git("hash-object", "-w", "x.bin").strip()

    def test_blobs_are_read_by_id_in_one_git_call(self):
        first, second = self.blob_id(b"one\n\ntwo"), self.blob_id(b"\x00 bytes\n")
        with mock.patch.object(gitio, "_git_bytes", wraps=gitio._git_bytes) as git:
            blobs = gitio.read_blobs(self.tmp, [first, second, first])
        self.assertEqual(blobs, {first: b"one\n\ntwo", second: b"\x00 bytes\n"})
        self.assertEqual(git.call_count, 1)

    def test_no_blob_needs_no_git_call(self):
        with mock.patch.object(gitio, "_git_bytes", side_effect=AssertionError("git was asked")):
            self.assertEqual(gitio.read_blobs(self.tmp, []), {})

    def test_an_id_that_names_no_object_is_a_git_error(self):
        present, missing = self.blob_id(b"one\n"), "0" * 39 + "1"
        with self.assertRaises(gitio.GitError) as caught:
            gitio.read_blobs(self.tmp, [present, missing])
        self.assertIn(missing, str(caught.exception))

    def test_an_answer_not_shaped_as_asked_is_a_git_error(self):
        oid = self.blob_id(b"one\n")
        header = oid.encode()
        for answer in (b"", header + b" blob\n", header + b" blob 9\none\n", header + b" tree 4\none\n\n"):
            with mock.patch.object(gitio, "_git_bytes", return_value=answer):
                with self.assertRaises(gitio.GitError, msg=answer):
                    gitio.read_blobs(self.tmp, [oid])

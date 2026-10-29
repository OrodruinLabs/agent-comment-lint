"""Judging one file: scope by extension, findings in a fixed order, and filtering to changed ranges."""
import unittest
from unittest import mock

from agent_comment_lint import engine, lexers
from agent_comment_lint.rules import Finding
from support import LONG


class TestCheckText(unittest.TestCase):
    def test_findings_come_ordered_by_line_and_then_by_rule(self):
        text = "// see ADR-0001 %s\nint x;\n// one\n// two see ADR-0002\n" % LONG
        found = [(finding.line, finding.rule) for finding in engine.check_text("a.cs", text).findings]
        self.assertEqual(found, [(1, "C3"), (1, "C7"), (3, "C1"), (4, "C3")])

    def test_a_block_finding_carries_the_span_it_covers(self):
        finding = engine.check_text("a.cs", "int x;\n// one\n// two\n// three\n").findings[0]
        self.assertEqual((finding.rule, finding.line, finding.end_line), ("C1", 2, 4))

    def test_a_path_outside_the_scope_is_refused(self):
        self.assertFalse(engine.in_scope("notes.md"))
        with self.assertRaises(ValueError):
            engine.check_text("notes.md", "// one\n// two\n")

    def test_unresolved_lines_are_counted(self):
        self.assertEqual(engine.check_text("a.cs", 'var s = @"opens\nand closes";\n').unresolved_lines, 2)


class TestFamilyForNames(unittest.TestCase):
    NAMED = lexers.Family("named", (".nm",), lexers.Markers(True, False, False, False), None,
                          ("Dockerfile", "Makefile"))

    def setUp(self):
        patcher = mock.patch.object(lexers, "FAMILIES", lexers.FAMILIES + (self.NAMED,))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_file_is_matched_by_its_exact_name(self):
        self.assertIs(lexers.family_for("ops/Dockerfile"), self.NAMED)
        self.assertIs(lexers.family_for("Makefile"), self.NAMED)

    def test_a_name_behind_a_backslash_is_matched_too(self):
        self.assertIs(lexers.family_for("ops\\Dockerfile"), self.NAMED)

    def test_a_name_that_only_contains_a_covered_name_is_not_matched(self):
        for path in ("Makefile.bak", "MyDockerfile", "Dockerfile.orig", "ops/dockerfile"):
            self.assertIsNone(lexers.family_for(path), path)


class TestWithin(unittest.TestCase):
    BLOCK = Finding("C1", 10, 14, "5-line prose block (limit 1)")

    def test_a_finding_is_kept_when_any_of_its_lines_changed(self):
        for ranges in ([(10, 10)], [(14, 20)], [(1, 10)], [(12, 12)], [(1, 2), (13, 13)]):
            self.assertEqual(engine.within([self.BLOCK], ranges), [self.BLOCK], ranges)

    def test_a_finding_is_dropped_when_none_of_its_lines_changed(self):
        for ranges in ([], [(1, 9)], [(15, 30)], [(1, 9), (15, 30)]):
            self.assertEqual(engine.within([self.BLOCK], ranges), [], ranges)

"""False positives both earlier copies had, pinned as they are today so that changing one is a decision."""
import unittest

from support import LONG, found


class TestALeadingStarInLineLexedCode(unittest.TestCase):
    WRAPPED = "var x = a\n    * b\n    * c;\n"

    def test_a_wrapped_multiplication_in_csharp_is_a_prose_block(self):
        self.assertEqual(found("a.cs", self.WRAPPED), [("C1", 2)])

    def test_a_wrapped_multiplication_in_hcl_is_a_prose_block(self):
        self.assertEqual(found("main.tf", "x = a\n    * b\n    * c\n"), [("C1", 2)])


class TestDocsPathHasNoLeftAnchor(unittest.TestCase):
    def test_a_web_address_that_holds_a_docs_segment_is_a_governance_reference(self):
        address = "https://developer.mozilla.org/en-US/docs/Web/API/fetch"
        for path, comment in (("a.ts", "// "), ("a.cs", "// "), ("a.py", "# "), ("a.yml", "# ")):
            self.assertEqual(found(path, comment + address + "\n"), [("C3", 1)], path)


class TestAnyUnquotedHashOpensAComment(unittest.TestCase):
    def test_a_parameter_expansion_that_strips_a_docs_prefix_is_a_governance_reference(self):
        self.assertEqual(found("run.sh", "x=${y#docs/prefix}\n"), [("C3", 1)])
        self.assertEqual(found("pipeline.yml", "  - script: x=${y#docs/prefix}\n"), [("C3", 1)])
        self.assertEqual(found("main.tf", "x = replace(y, #docs/prefix\n"), [("C3", 1)])

    def test_a_long_line_that_counts_its_arguments_is_an_overlong_comment_line(self):
        self.assertEqual(found("run.sh", 'if [ $# -lt 2 ]; then echo "%s"; fi\n' % LONG), [("C7", 1)])
        self.assertEqual(found("pipeline.yml", '  - script: test $# -lt 2 || echo "%s"\n' % LONG), [("C7", 1)])


class TestCsharpVerbatimStringBody(unittest.TestCase):
    def test_comment_shaped_lines_inside_a_multi_line_verbatim_string_are_a_prose_block(self):
        text = 'var sql = @"select 1\n// one\n// two\n";\nint x;\n'
        self.assertEqual(found("a.cs", text), [("C1", 2)])

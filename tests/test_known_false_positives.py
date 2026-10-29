"""False positives both earlier copies had, pinned as they are today so that changing one is a decision."""
import unittest

from agent_comment_lint import engine, governance
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



class TestAgentContextFalsePositivesInCpython(unittest.TestCase):
    """Two CPython comments that the agent-context pack flags, pinned because that pack is opt-in."""

    AGENT_CONTEXT = governance.matcher(("agent-context",))

    def test_as_requested_in_a_cpython_comment_is_a_governance_reference(self):
        # The pins hold because the core never flags these, and only the opt-in pack does.
        text = "# which is calling CloseHandle as requested in [1], so there is nothing\n"
        self.assertEqual(engine.check_text("a.py", text, self.AGENT_CONTEXT).findings[0].message,
                         "governance reference 'as requested'")

    def test_per_the_spec_in_a_cpython_comment_is_a_governance_reference(self):
        text = "# Map conditions (per the spec) to signals\n"
        self.assertEqual(engine.check_text("a.py", text, self.AGENT_CONTEXT).findings[0].message,
                         "governance reference 'per the spec'")


class TestRubyLiteralsTheLineScannerDoesNotKnow(unittest.TestCase):
    def test_a_character_literal_of_a_hash_reads_a_comment(self):
        # The line scanner does not know Ruby's `?#` character literal.
        self.assertEqual(found("a.rb", "x = ?#docs/prefix\n"), [("C3", 1)])

    def test_a_percent_word_list_with_a_hash_reads_a_comment(self):
        # The line scanner does not know Ruby's percent literals.
        self.assertEqual(found("a.rb", "%w[a #docs/prefix]\n"), [("C3", 1)])

    def test_a_regex_literal_with_a_hash_reads_a_comment(self):
        # The line scanner does not know Ruby's regex literals.
        self.assertEqual(found("a.rb", "/#docs/prefix/ =~ s\n"), [("C3", 1)])

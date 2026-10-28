"""Behaviour both earlier copies relied on and neither tested, pinned so a change to it is a decision."""
import unittest

from agent_comment_lint.governance import first_reference
from agent_comment_lint.lexers import LexError, family_for
from agent_comment_lint.lexers.linescan import scan_line
from support import found


class TestBlockBoundaries(unittest.TestCase):
    def test_a_block_comment_right_after_a_line_comment_is_its_own_block(self):
        self.assertEqual(found("a.cs", "// one\n/*\n * two\n */\nint x;\n"), [])

    def test_a_line_comment_right_after_a_block_comment_is_its_own_block(self):
        self.assertEqual(found("a.cs", "/*\n * one\n */\n// two\nint x;\n"), [])

    def test_one_line_block_comments_never_add_up(self):
        self.assertEqual(found("a.cs", "/* one */\n/* two */\nint x;\n"), [])

    def test_the_closing_line_of_a_block_opened_after_code_is_not_prose(self):
        self.assertEqual(found("a.cs", "int x; /* one\n * two\n */\nint y;\n"), [])

    def test_a_line_lexed_block_opened_after_code_is_scored_only_from_its_star_lines(self):
        text = "foo(); /* this is a long\n explanation that wraps\n across lines */\n"
        self.assertEqual(found("a.cs", text), [])
        self.assertEqual(found("main.tf", text), [])
        self.assertEqual(found("a.cs", "foo(); /* one\n * two\n * three\n */\n"), [("C1", 2)])

    def test_a_line_lexed_block_comment_that_never_closes_is_not_refused(self):
        self.assertEqual(found("a.cs", "int x; /* never closes\n// see ADR-0001\n"), [("C3", 2)])
        self.assertEqual(found("main.tf", "x = 1 /* never closes\n"), [])

    def test_complete_tags_inside_a_block_comment_do_not_count(self):
        text = "/**\n * <summary>Signs it.</summary>\n * <returns>The envelope.</returns>\n */\n"
        self.assertEqual(found("a.cs", text), [])

    def test_a_jsx_comment_that_spans_lines_is_one_block(self):
        self.assertEqual(found("a.tsx", "const e = <div>\n  {/*\n  one\n  two\n  */}\n</div>;\n"), [("C1", 3)])


class TestLineScanner(unittest.TestCase):
    def test_an_escaped_quote_does_not_end_a_csharp_string(self):
        self.assertEqual(found("a.cs", 'var s = "a\\" // b"; // see ADR-0001\n'), [("C3", 1)])
        self.assertEqual(scan_line('var s = "a\\" // b";', hash_marker=False, slash_marker=True),
                         [("code", "var s = "), ("string", '"a\\" // b"'), ("code", ";")])

    def test_doubled_braces_in_an_interpolated_string_open_no_hole(self):
        self.assertEqual(found("a.cs", 'var s = $"{{"; // see ADR-0001\n'), [("C3", 1)])

    def test_a_doubled_quote_stays_inside_a_single_quoted_scalar(self):
        self.assertEqual(scan_line("k: 'it''s' # c", hash_marker=True, slash_marker=False),
                         [("code", "k: "), ("string", "'it''s'"), ("code", " "), ("comment", "# c")])

    def test_adjacent_text_of_one_kind_is_one_segment(self):
        segments = family_for("a.ts").lex("const a = `x`;")[0].segments
        self.assertEqual(segments, [("code", "const a = "), ("string", "`x`"), ("code", ";")])


class TestHashOnlyLanguages(unittest.TestCase):
    def test_a_double_slash_is_never_a_comment_in_yaml_or_shell(self):
        self.assertEqual(found("a.yml", "url: http://host/ADR-0001\n"), [])
        self.assertEqual(found("a.sh", "echo a // see ADR-0001\n"), [])


class TestAssertionMessages(unittest.TestCase):
    OPENING = 'x.Should().Be(1,\n    because: "one"\n'

    def test_a_two_line_message_is_within_the_budget(self):
        self.assertEqual(found("a.cs", self.OPENING + '        + " two");\n'), [])

    def test_a_three_line_message_is_reported_on_its_opening_line(self):
        self.assertEqual(found("a.cs", self.OPENING + '        + " two"\n        + " three");\n'), [("C5", 2)])


class TestHeredocShapes(unittest.TestCase):
    def test_an_indented_terminator_closes_the_heredoc(self):
        self.assertEqual(found("run.sh", "cat <<-EOF\n\t# one\n\t# two\n\tEOF\n# see ADR-0001\n"), [("C3", 5)])

    def test_a_quoted_terminator_opens_a_heredoc(self):
        self.assertEqual(found("run.sh", "cat <<'EOF'\n# one\n# two\nEOF\n"), [])


class TestRawStringShapes(unittest.TestCase):
    def test_a_longer_quote_run_closes_only_on_a_run_as_long(self):
        text = 'var s = """"\n// see ADR-0001 """ inside\n"""";\n// see ADR-0002\n'
        self.assertEqual(found("a.cs", text), [("C3", 4)])

    def test_an_unclosed_longer_run_is_refused(self):
        with self.assertRaises(LexError):
            found("a.cs", 'var s = """"\nbody\n""";\n')


class TestDocstringBodies(unittest.TestCase):
    def test_the_opening_delimiter_is_not_part_of_the_prose(self):
        self.assertEqual(found("a.py", 'def f():\n    """@param a one\n    @param b two\n    Prose."""\n'), [])

    def test_the_closing_delimiter_is_not_part_of_the_prose(self):
        self.assertEqual(found("a.py", 'def f():\n    """Prose.\n    <a>one</a>"""\n'), [])

    def test_a_single_quoted_docstring_is_found_without_a_parse(self):
        text = "    def f(self):\n        '''One.\n        Two.'''\n        return (\n"
        self.assertEqual(found("a.py", text), [("C1", 2)])


class TestGovernanceForms(unittest.TestCase):
    def test_forms_only_the_older_patterns_catch(self):
        for comment, reference in (("see FEAT-12", "FEAT-12"), ("see FEAT-AUTH", "FEAT-AUTH"),
                                   ("see TRD-3a", "TRD-3a"), ("see PATCH-2", "PATCH-2")):
            self.assertEqual(first_reference(comment), reference, comment)

    def test_a_lower_case_slug_is_not_a_decision_record(self):
        self.assertIsNone(first_reference("the adr-0009 folder slug"))

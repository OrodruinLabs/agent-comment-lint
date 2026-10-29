"""Dockerfile lexing: whole-line `#` comments, parser directives and heredoc payload."""
import unittest

from agent_comment_lint.lexers import LexError, family_for
from support import comments, found


class TestScope(unittest.TestCase):
    def test_dockerfile_and_containerfile_are_covered_by_name(self):
        self.assertEqual(found("Dockerfile", "# ADR-9\n"), [("C3", 1)])
        self.assertEqual(found("build/Containerfile", "# ADR-9\n"), [("C3", 1)])

    def test_the_dockerfile_extension_is_covered(self):
        self.assertEqual(family_for("app.dockerfile").name, "dockerfile")

    def test_a_name_that_only_ends_in_dockerfile_is_not_covered(self):
        self.assertIsNone(family_for("MyDockerfile"))


class TestComments(unittest.TestCase):
    def test_a_hash_after_an_instruction_is_not_a_comment(self):
        self.assertEqual(found("Dockerfile", "RUN echo hi # see ADR-9\n"), [])

    def test_a_two_line_comment_is_one_block(self):
        self.assertEqual(found("Dockerfile", "# one\n# two\nFROM x\n"), [("C1", 1)])

    def test_an_indented_comment_is_a_comment(self):
        self.assertEqual(found("Dockerfile", "FROM x\n  # see ADR-9\n"), [("C3", 2)])

    def test_a_comment_inside_a_continued_instruction_is_judged(self):
        text = "RUN a \\\n    # see ADR-9\n    && b\n"
        self.assertEqual(found("Dockerfile", text), [("C3", 2)])


class TestParserDirectives(unittest.TestCase):
    def test_parser_directives_are_not_prose(self):
        self.assertEqual(found("Dockerfile", "# syntax=docker/dockerfile:1\n# one line\nFROM x\n"), [])

    def test_directives_ignore_case_and_space_around_the_equals_sign(self):
        text = "# Syntax = docker/dockerfile:1\n# CHECK=skip=all\n# one line\nFROM x\n"
        self.assertEqual(comments("Dockerfile", text), [[], [], ["# one line"], []])

    def test_a_directive_after_a_comment_is_prose(self):
        self.assertEqual(found("Dockerfile", "# one\n# syntax=x\nFROM x\n"), [("C1", 1)])

    def test_a_directive_after_an_instruction_is_prose(self):
        self.assertEqual(found("Dockerfile", "FROM x\n# syntax=a\n# check=b\n"), [("C1", 2)])

    def test_a_directive_after_a_blank_line_is_prose(self):
        self.assertEqual(found("Dockerfile", "\n# syntax=a\n# check=b\nFROM x\n"), [("C1", 2)])


class TestEscapeDirective(unittest.TestCase):
    def test_a_backtick_escape_continues_an_instruction_into_a_heredoc(self):
        text = "# escape=`\nRUN a `\n  <<EOF\n# ADR-9\nEOF\n"
        self.assertEqual(found("Dockerfile", text), [])

    def test_a_backslash_does_not_continue_under_a_backtick_escape(self):
        text = "# escape=`\nRUN a \\\n# see ADR-9\n"
        self.assertEqual(found("Dockerfile", text), [("C3", 3)])


class TestHeredocs(unittest.TestCase):
    def test_heredoc_payload_is_content(self):
        self.assertEqual(found("Dockerfile", "RUN <<EOF\n# ADR-9\nEOF\n"), [])

    def test_copy_heredoc_payload_is_content(self):
        self.assertEqual(found("Dockerfile", "COPY <<EOF /dst\n# ADR-9\nEOF\n"), [])

    def test_a_dash_heredoc_ends_at_a_tab_indented_terminator(self):
        self.assertEqual(found("Dockerfile", "RUN <<-EOF\n# ADR-9\n\tEOF\n# see ADR-8\n"), [("C3", 4)])

    def test_several_heredocs_on_one_line_are_all_content(self):
        text = "RUN <<A <<B\n# ADR-1\nA\n# ADR-2\nB\n# see ADR-3\n"
        self.assertEqual(found("Dockerfile", text), [("C3", 6)])

    def test_a_heredoc_starts_after_the_continued_instruction_ends(self):
        text = "RUN cat <<EOF \\\n  > /x\n# ADR-9\nEOF\n"
        self.assertEqual(found("Dockerfile", text), [])

    def test_a_heredoc_marker_in_a_string_opens_nothing(self):
        self.assertEqual(found("Dockerfile", 'RUN echo "<<EOF"\n# see ADR-9\n'), [("C3", 2)])

    def test_a_heredoc_marker_on_another_instruction_opens_nothing(self):
        self.assertEqual(found("Dockerfile", "LABEL a=<<EOF\n# see ADR-9\n"), [("C3", 2)])

    def test_an_onbuild_heredoc_payload_is_content(self):
        self.assertEqual(found("Dockerfile", "ONBUILD RUN <<EOF\n# ADR-9\nEOF\n# see ADR-8\n"), [("C3", 4)])

    def test_an_onbuild_without_a_heredoc_instruction_opens_nothing(self):
        self.assertEqual(found("Dockerfile", "ONBUILD <<EOF\n# see ADR-9\n"), [("C3", 2)])

    def test_an_unterminated_heredoc_cannot_be_lexed(self):
        with self.assertRaises(LexError) as caught:
            family_for("Dockerfile").lex("FROM x\nRUN <<EOF\nx\n")
        self.assertEqual(caught.exception.line, 2)

    def test_an_unterminated_second_heredoc_reports_its_opening_line(self):
        with self.assertRaises(LexError) as caught:
            family_for("Dockerfile").lex("RUN <<A <<B\nx\nA\n")
        self.assertEqual(caught.exception.line, 1)


if __name__ == "__main__":
    unittest.main()

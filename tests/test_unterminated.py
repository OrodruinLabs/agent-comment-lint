"""A construct that never closes stops the scan with its line; nothing below it is silently passed."""
import unittest

from agent_comment_lint.lexers import LexError
from support import found


class TestHeredocs(unittest.TestCase):
    def test_an_unclosed_heredoc_in_yaml_is_refused(self):
        with self.assertRaises(LexError) as caught:
            found("pipeline.yml", "steps:\n  - script: |\n      cat <<EOF\n      never closes\n")
        self.assertEqual(caught.exception.line, 3)

    def test_an_unclosed_heredoc_in_hcl_is_refused(self):
        with self.assertRaises(LexError) as caught:
            found("main.tf", 'locals {\n  body = <<-EOT\n    never closes\n}\n')
        self.assertEqual(caught.exception.line, 2)

    def test_a_closed_heredoc_masks_only_its_payload(self):
        text = "cat <<EOF\n# one\n# two\nEOF\n# see ADR-0001\n"
        self.assertEqual(found("run.sh", text), [("C3", 5)])

    def test_a_shift_inside_shell_arithmetic_is_not_a_heredoc(self):
        text = "mask=$((1 << width))\n# see ADR-0001\n"
        self.assertEqual(found("run.sh", text), [("C3", 2)])

    def test_a_heredoc_token_inside_a_comment_is_not_a_heredoc(self):
        self.assertEqual(found("run.sh", "# usage: cat <<EOF\necho hi\n# see ADR-0001\n"), [("C3", 3)])


class TestPython(unittest.TestCase):
    def test_an_unclosed_triple_quote_in_text_that_does_not_parse_is_refused(self):
        with self.assertRaises(LexError) as caught:
            found("a.py", 'x = 1\ny = """\nnever closes\n# see ADR-0001\n')
        self.assertEqual(caught.exception.line, 2)

    def test_text_that_parses_is_never_refused_over_a_stray_triple_quote(self):
        text = "x = '\\'\"\"\"'\n# see ADR-0001\n"
        compile(text, "a.py", "exec")
        self.assertEqual(found("a.py", text), [("C3", 2)])

    def test_a_shift_is_not_a_heredoc_in_python(self):
        self.assertEqual(found("a.py", "x = 1 << EOF\n# see ADR-0001\n"), [("C3", 2)])

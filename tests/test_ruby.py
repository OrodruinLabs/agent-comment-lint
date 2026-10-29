"""Ruby lexing: `#` comments, heredoc payload and `=begin` blocks."""
import unittest

from agent_comment_lint import engine
from agent_comment_lint.lexers import LexError, family_for
from support import comments, found


class TestScope(unittest.TestCase):
    def test_extensions_and_names_are_covered(self):
        for name in ("a.rb", "a.rake", "a.gemspec", "Gemfile", "lib/Rakefile"):
            self.assertEqual(family_for(name).name, "ruby", name)

    def test_files_named_gemfile_and_rakefile_are_covered(self):
        self.assertEqual(found("Gemfile", "# one\n# two\n"), [("C1", 1)])
        self.assertEqual(found("Rakefile", "# one\n# two\n"), [("C1", 1)])

    def test_a_longer_name_is_not_covered(self):
        self.assertIsNone(family_for("MyGemfile"))


class TestComments(unittest.TestCase):
    def test_a_two_line_comment_is_one_block(self):
        self.assertEqual(found("a.rb", "# one\n# two\nx = 1\n"), [("C1", 1)])

    def test_interpolation_and_hashes_in_strings_are_not_comments(self):
        self.assertEqual(comments("a.rb", 'puts "#{name} # ADR-9"\n'), [[]])

    def test_a_trailing_comment_is_reported(self):
        self.assertEqual(found("a.rb", "x = 1 # see ADR-9\n"), [("C3", 1)])


class TestHeredocs(unittest.TestCase):
    def test_heredoc_payload_is_content(self):
        self.assertEqual(found("a.rb", "s = <<~EOS\n  # ADR-9\nEOS\n"), [])

    def test_an_append_is_not_a_heredoc(self):
        self.assertEqual(found("a.rb", "items << EOS\n# see ADR-9\n"), [("C3", 2)])

    def test_an_append_of_a_word_is_not_a_heredoc(self):
        self.assertEqual(found("a.rb", "items<<EOS\n# see ADR-9\n"), [("C3", 2)])
        self.assertEqual(found("a.rb", "f(x)<<EOS\n# see ADR-9\n"), [("C3", 2)])

    def test_the_opener_after_a_paren_comma_or_equals_is_a_heredoc(self):
        for opener in ("f(<<~EOS)", "f(a, <<-EOS)", "s=<<EOS"):
            self.assertEqual(found("a.rb", opener + "\n# ADR-9\nEOS\n"), [], opener)

    def test_a_quoted_identifier_opens_a_heredoc(self):
        self.assertEqual(found("a.rb", "s = <<~'EOS'\n# ADR-9\nEOS\n"), [])
        self.assertEqual(found("a.rb", 's = <<-"EOS"\n# ADR-9\n  EOS\n'), [])

    def test_a_squiggly_or_dash_terminator_may_be_indented(self):
        self.assertEqual(found("a.rb", "s = <<~EOS\n# ADR-9\n  EOS\n# see ADR-8\n"), [("C3", 4)])
        self.assertEqual(found("a.rb", "s = <<-EOS\n# ADR-9\n  EOS\n# see ADR-8\n"), [("C3", 4)])

    def test_a_plain_terminator_must_start_at_column_zero(self):
        with self.assertRaises(LexError):
            engine.check_text("a.rb", "s = <<EOS\n# ADR-9\n  EOS\n")

    def test_a_heredoc_in_a_string_or_comment_opens_nothing(self):
        self.assertEqual(found("a.rb", 'x = "<<EOS"\n# see ADR-9\n'), [("C3", 2)])
        self.assertEqual(found("a.rb", "x = 1 # <<EOS\n# see ADR-9\n"), [("C3", 2)])

    def test_an_unterminated_heredoc_cannot_be_lexed(self):
        with self.assertRaises(LexError):
            engine.check_text("a.rb", "s = <<~EOS\nnever closed\n")


class TestBeginEnd(unittest.TestCase):
    def test_a_begin_end_block_is_one_block(self):
        self.assertEqual(found("a.rb", "=begin\none\ntwo\n=end\nx = 1\n"), [("C1", 2)])

    def test_a_governance_reference_inside_a_begin_end_block_is_reported(self):
        self.assertEqual(found("a.rb", "=begin\nsee ADR-9\n=end\n"), [("C3", 2)])

    def test_an_indented_begin_is_not_a_block(self):
        self.assertEqual(found("a.rb", "  =begin\n  one\n  two\n  =end\n"), [])

    def test_begin_inside_a_heredoc_is_content(self):
        self.assertEqual(found("a.rb", "s = <<~EOS\n=begin\none\ntwo\nEOS\n"), [])

    def test_an_unterminated_begin_cannot_be_lexed(self):
        with self.assertRaises(LexError) as caught:
            engine.check_text("a.rb", "x = 1\n=begin\nnever closed\n")
        self.assertEqual(caught.exception.line, 2)


if __name__ == "__main__":
    unittest.main()

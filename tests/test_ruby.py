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

    def test_a_shebang_is_not_prose(self):
        self.assertEqual(found("a.rb", "#!/usr/bin/env ruby\n# frozen_string_literal: true\n\nputs 1\n"), [])

    def test_a_shebang_after_the_first_line_is_a_comment(self):
        self.assertEqual(found("a.rb", "x = 1\n#!/usr/bin/env ruby\n# one\n"), [("C1", 2)])


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

    def test_a_singleton_class_opener_is_not_a_heredoc(self):
        for opener in ("class <<self", "class << self", "class  <<self", "class\t<<self"):
            text = "class Foo\n  " + opener + "\n    def x; end\n  end\nend\n"
            self.assertEqual(found("a.rb", text), [], opener)

    def test_the_opener_after_a_bracket_brace_or_operator_is_a_heredoc(self):
        self.assertEqual(found("a.rb", "find_by_sql([<<~SQL, id])\n  #{a}\n  #{b}\nSQL\n"), [])
        self.assertEqual(found("a.rb", "x = [<<~SQL, 1]\n  # select see ADR-7\nSQL\n"), [])
        for opener in ("h = {<<~EOS => 1}", "x = !<<~EOS", "a &&<<~EOS", "a ||<<~EOS", "a = 1;<<~EOS"):
            self.assertEqual(found("a.rb", opener + "\n# see ADR-7\nEOS\n"), [], opener)

    def test_the_opener_after_a_unary_sign_is_a_heredoc(self):
        self.assertEqual(found("a.rb", "s = +<<~EOS\n  # one\n  # two\nEOS\n"), [])
        self.assertEqual(found("a.rb", "s = -<<~EOS\n  # see ADR-7\nEOS\n"), [])

    def test_a_sign_after_a_word_is_not_a_unary_sign(self):
        self.assertEqual(found("a.rb", "x = a+<<b\n# see ADR-7\n"), [("C3", 2)])

    def test_the_symbol_for_the_append_method_opens_nothing(self):
        self.assertEqual(found("a.rb", "alias_method :<<, :push\n# see ADR-7\n"), [("C3", 2)])
        self.assertEqual(found("a.rb", "send(:<<EOS)\n# see ADR-7\n"), [("C3", 2)])


class TestDataSection(unittest.TestCase):
    def test_the_lines_after_end_are_not_source(self):
        self.assertEqual(found("a.rb", "puts DATA.read\n__END__\n=begin\nfoo\n"), [])
        self.assertEqual(found("a.rb", "puts DATA.read\n__END__\ncat <<EOF\n"), [])
        self.assertEqual(found("a.rb", "x = 1\n__END__\n# see ADR-7\n"), [])

    def test_a_crlf_end_line_ends_the_source(self):
        self.assertEqual(found("a.rb", "x = 1\r\n__END__\r\n# see ADR-7\r\n"), [])

    def test_end_must_fill_its_line(self):
        self.assertEqual(found("a.rb", "x = 1\n__END__ \n# see ADR-7\n"), [("C3", 3)])
        self.assertEqual(found("a.rb", "x = 1\n  __END__\n# see ADR-7\n"), [("C3", 3)])

    def test_end_inside_a_heredoc_is_payload(self):
        self.assertEqual(found("a.rb", "s = <<~EOS\n__END__\nEOS\n# see ADR-7\n"), [("C3", 4)])


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

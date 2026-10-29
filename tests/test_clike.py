"""The C-family lexer, read with every option off and then with each option on alone."""
import unittest

from agent_comment_lint import rules
from agent_comment_lint.lexers import LexError, clike

PLAIN = clike.Syntax(nested_blocks=False, multiline_strings=False, raw_string=None, text_block=False,
                     char_literal="simple", line_continuation=False)


def found(syntax, text):
    """(rule, line) for every finding in `text`, read by the C-family lexer that `syntax` configures."""
    lexed = clike.lexer(syntax)(text)
    return [(finding.rule, finding.line) for finding in rules.check(text.splitlines(), lexed, clike.MARKERS)]


def comments(syntax, text):
    """The comment segments of each line, as the lexer that `syntax` configures sees them."""
    return [[part for kind, part in line.segments if kind == "comment"] for line in clike.lexer(syntax)(text)]


class TestPlain(unittest.TestCase):
    def test_a_slash_pair_in_a_string_is_not_a_comment(self):
        self.assertEqual(comments(PLAIN, 's = "http://host/ADR-9";\n'), [[]])
        self.assertEqual(found(PLAIN, 's = "http://host/ADR-9";\n'), [])

    def test_a_multi_line_block_comment_is_one_block(self):
        self.assertEqual(found(PLAIN, "/* one\n   two */\nint x;\n"), [("C1", 1)])

    def test_an_unterminated_block_comment_cannot_be_lexed(self):
        with self.assertRaises(LexError) as caught:
            found(PLAIN, "int x;\n/* one\n   two\n")
        self.assertEqual(caught.exception.line, 2)

    def test_an_unterminated_string_cannot_be_lexed(self):
        with self.assertRaises(LexError) as caught:
            found(PLAIN, 'int x;\ns = "abc;\n// see ADR-9\n')
        self.assertEqual(caught.exception.line, 2)

    def test_an_unterminated_character_literal_cannot_be_lexed(self):
        with self.assertRaises(LexError) as caught:
            found(PLAIN, "int x;\nc = 'a;\n")
        self.assertEqual(caught.exception.line, 2)

    def test_windows_line_endings_lex_like_newlines(self):
        text = "// one\n// two\nint x;\n"
        self.assertEqual(found(PLAIN, text.replace("\n", "\r\n")), found(PLAIN, text))
        self.assertEqual(found(PLAIN, text), [("C1", 1)])

    def test_a_slash_pair_in_a_character_literal_is_not_a_comment(self):
        self.assertEqual(comments(PLAIN, "c = '/'; d = '\\''; // see ADR-9\n"), [["// see ADR-9"]])

    def test_quotes_of_the_other_kind_are_content(self):
        text = "c = '\"'; s = \"'\"; t = \"it's\"; // see ADR-9\n"
        self.assertEqual(comments(PLAIN, text), [["// see ADR-9"]])

    def test_an_escaped_quote_does_not_end_the_string(self):
        self.assertEqual(comments(PLAIN, 's = "a \\" // b"; // see ADR-9\n'), [["// see ADR-9"]])

    def test_a_block_opener_in_a_line_comment_is_comment_text(self):
        self.assertEqual(found(PLAIN, "// a /* b\nint x; // see ADR-9\n"), [("C3", 2)])

    def test_a_line_comment_inside_a_block_comment_is_block_text(self):
        self.assertEqual(comments(PLAIN, "/* // */ int x; // see ADR-9\n"), [["/* // */", "// see ADR-9"]])

    def test_block_comments_do_not_nest(self):
        self.assertEqual(found(PLAIN, "/* a /* b */\nint x; // see ADR-9\n"), [("C3", 2)])

    def test_block_delimiters_in_strings_are_content(self):
        self.assertEqual(found(PLAIN, 's = "/*";\n// see ADR-9\nt = "*/";\n'), [("C3", 2)])

    def test_a_block_close_in_a_string_after_a_closed_block_is_content(self):
        text = '/* one\n   two */ s = "*/"; // see ADR-9\n'
        self.assertEqual(comments(PLAIN, text), [["/* one"], ["   two */", "// see ADR-9"]])
        self.assertEqual(found(PLAIN, text), [("C1", 1), ("C3", 2)])

    def test_code_and_a_comment_after_a_block_close_are_read(self):
        text = "/* one\n   two */ int x; // see ADR-9\n// three\n"
        self.assertEqual(found(PLAIN, text), [("C1", 1), ("C3", 2)])

    def test_an_empty_text_has_no_lines(self):
        self.assertEqual(clike.lexer(PLAIN)(""), [])

    def test_a_text_without_a_final_newline_is_read_to_its_end(self):
        self.assertEqual(found(PLAIN, "int x;\n// see ADR-9"), [("C3", 2)])

    def test_a_backtick_is_code_without_raw_strings(self):
        self.assertEqual(found(PLAIN, "x = `a; // see ADR-9\n"), [("C3", 1)])


class TestNestedBlocks(unittest.TestCase):
    NESTED = PLAIN._replace(nested_blocks=True)

    def test_an_inner_block_does_not_close_the_outer_one(self):
        text = "/* a /* b */ c\n   d */\nint x;\n"
        self.assertEqual(comments(self.NESTED, text), [["/* a /* b */ c"], ["   d */"], []])
        self.assertEqual(found(self.NESTED, text), [("C1", 1)])

    def test_an_unclosed_outer_block_cannot_be_lexed(self):
        with self.assertRaises(LexError) as caught:
            found(self.NESTED, "int x;\n/* a /* b */\nint y;\n")
        self.assertEqual(caught.exception.line, 2)

    def test_code_after_the_outer_close_is_code(self):
        text = "/* a /* b */ c */ int x; // see ADR-9\n"
        self.assertEqual(comments(self.NESTED, text), [["/* a /* b */ c */", "// see ADR-9"]])

    def test_a_comment_after_an_outer_close_that_follows_an_inner_one_starts_the_next_block(self):
        self.assertEqual(found(self.NESTED, "/* a\n   /* b */ c */ // d\n// e\n"), [("C1", 1), ("C1", 2)])

    def test_slashes_after_an_inner_close_on_the_closing_line_are_block_text(self):
        self.assertEqual(found(self.NESTED, "/* a\n   /* b */ // c */\n// d\n"), [("C1", 1)])

    def test_code_after_an_outer_close_that_follows_an_inner_one_ends_the_block(self):
        self.assertEqual(found(self.NESTED, "/* a\n   /* b */ c */ x // d\n// e\n"), [("C1", 1)])


class TestMultilineStrings(unittest.TestCase):
    MULTILINE = PLAIN._replace(multiline_strings=True)

    def test_a_plain_string_may_cross_lines(self):
        self.assertEqual(found(self.MULTILINE, 's = "a\n// ADR-9\n// two\n";\n'), [])

    def test_a_plain_string_may_not_cross_lines_by_default(self):
        with self.assertRaises(LexError) as caught:
            found(PLAIN, 's = "a\n// ADR-9\n";\n')
        self.assertEqual(caught.exception.line, 1)

    def test_an_unterminated_multi_line_string_cannot_be_lexed(self):
        with self.assertRaises(LexError) as caught:
            found(self.MULTILINE, 'int x;\ns = "a\n// b\n')
        self.assertEqual(caught.exception.line, 2)


class TestBacktickRawStrings(unittest.TestCase):
    BACKTICK = PLAIN._replace(raw_string="backtick")

    def test_a_raw_string_across_lines_is_content(self):
        self.assertEqual(found(self.BACKTICK, "s = `\n// ADR-9\n// two\n`; // see ADR-9\n"), [("C3", 4)])

    def test_a_backslash_does_not_escape_the_closing_backtick(self):
        self.assertEqual(comments(self.BACKTICK, "s = `a\\` + `// b`; // see ADR-9\n"), [["// see ADR-9"]])

    def test_a_block_close_in_a_raw_string_is_content(self):
        self.assertEqual(found(self.BACKTICK, "s = `*/ /*`; // see ADR-9\n"), [("C3", 1)])

    def test_an_unterminated_raw_string_cannot_be_lexed(self):
        with self.assertRaises(LexError) as caught:
            found(self.BACKTICK, "int x;\ns = `x\n")
        self.assertEqual(caught.exception.line, 2)


class TestRustRawStrings(unittest.TestCase):
    RUST = PLAIN._replace(raw_string="rust")

    def test_a_backslash_is_content(self):
        self.assertEqual(found(self.RUST, 's = r"C:\\"; // see ADR-9\n'), [("C3", 1)])

    def test_a_quote_with_fewer_hashes_does_not_close(self):
        self.assertEqual(comments(self.RUST, 's = r##"a "# // ADR-9"##; // see ADR-9\n'), [["// see ADR-9"]])

    def test_byte_and_c_prefixes_open_raw_strings(self):
        self.assertEqual(found(self.RUST, 'a = br"\\"; b = cr#"\\"#; // see ADR-9\n'), [("C3", 1)])

    def test_a_raw_string_may_cross_lines(self):
        self.assertEqual(found(self.RUST, 's = r#"\n// ADR-9\n// two\n"#;\n'), [])

    def test_a_raw_identifier_is_code(self):
        self.assertEqual(found(self.RUST, "let r#type = 1; // see ADR-9\n"), [("C3", 1)])

    def test_a_longer_word_is_no_prefix(self):
        self.assertEqual(found(self.RUST, 'f(ur"a\\"b"); // see ADR-9\n'), [("C3", 1)])

    def test_an_unterminated_raw_string_cannot_be_lexed(self):
        with self.assertRaises(LexError) as caught:
            found(self.RUST, 'int x;\ns = r#"x"\n')
        self.assertEqual(caught.exception.line, 2)


class TestSwiftRawStrings(unittest.TestCase):
    SWIFT = PLAIN._replace(raw_string="swift")

    def test_a_backslash_is_content(self):
        self.assertEqual(found(self.SWIFT, 's = #"C:\\"#; // see ADR-9\n'), [("C3", 1)])

    def test_a_quote_with_fewer_hashes_does_not_close(self):
        self.assertEqual(comments(self.SWIFT, 's = ##"a "# // ADR-9"##; // see ADR-9\n'), [["// see ADR-9"]])

    def test_an_escaped_quote_does_not_close(self):
        self.assertEqual(comments(self.SWIFT, 's = #"a \\#"# // ADR-9"#; // see ADR-9\n'), [["// see ADR-9"]])

    def test_a_multi_line_raw_string_is_content(self):
        self.assertEqual(found(self.SWIFT, 's = #"""\n// ADR-9\n"# // two\n"""#\n'), [])

    def test_a_hash_without_a_quote_is_code(self):
        self.assertEqual(found(self.SWIFT, "#if DEBUG // see ADR-9\n"), [("C3", 1)])

    def test_a_one_line_raw_string_may_not_cross_lines(self):
        with self.assertRaises(LexError) as caught:
            found(self.SWIFT, 'int x;\ns = #"abc\n"#\n')
        self.assertEqual(caught.exception.line, 2)

    def test_an_unterminated_multi_line_raw_string_cannot_be_lexed(self):
        with self.assertRaises(LexError) as caught:
            found(self.SWIFT, 's = #"""\nabc\n"""\n')
        self.assertEqual(caught.exception.line, 1)


class TestCppRawStrings(unittest.TestCase):
    CPP = PLAIN._replace(raw_string="cpp")

    def test_a_close_with_another_delimiter_does_not_end_it(self):
        self.assertEqual(comments(self.CPP, 's = R"x(a)" // ADR-9)x"; // see ADR-9\n'), [["// see ADR-9"]])

    def test_a_quote_is_content(self):
        self.assertEqual(found(self.CPP, 's = R"(a"b)"; // see ADR-9\n'), [("C3", 1)])

    def test_encoding_prefixes_open_raw_strings(self):
        text = 'a = u8R"(" // x)"; b = LR"(" // x)"; c = uR"(" // x)"; d = UR"(" // x)"; // see ADR-9\n'
        self.assertEqual(comments(self.CPP, text), [["// see ADR-9"]])

    def test_a_raw_string_may_cross_lines(self):
        self.assertEqual(found(self.CPP, 's = R"(\n// ADR-9\n// two\n)";\n'), [])

    def test_a_quote_with_no_delimiter_after_it_is_a_plain_string(self):
        self.assertEqual(found(self.CPP, 's = R"a b"; // see ADR-9\n'), [("C3", 1)])

    def test_an_unterminated_raw_string_cannot_be_lexed(self):
        with self.assertRaises(LexError) as caught:
            found(self.CPP, 'int x;\ns = R"x(abc)";\n')
        self.assertEqual(caught.exception.line, 2)


class TestTextBlocks(unittest.TestCase):
    TEXT_BLOCK = PLAIN._replace(text_block=True)

    def test_a_text_block_is_content(self):
        self.assertEqual(found(self.TEXT_BLOCK, 's = """\n// ADR-9\n// two\n""";\n'), [])

    def test_an_escaped_quote_run_does_not_close(self):
        self.assertEqual(found(self.TEXT_BLOCK, 's = """\na \\""" // ADR-9\n""";\n'), [])

    def test_a_closing_run_of_more_quotes_is_one_close(self):
        self.assertEqual(found(self.TEXT_BLOCK, 's = """\na""""; // see ADR-9\n'), [("C3", 2)])

    def test_an_unterminated_text_block_cannot_be_lexed(self):
        with self.assertRaises(LexError) as caught:
            found(self.TEXT_BLOCK, 'int x;\ns = """\nx\n')
        self.assertEqual(caught.exception.line, 2)

    def test_three_quotes_are_two_strings_without_text_blocks(self):
        with self.assertRaises(LexError) as caught:
            found(PLAIN, 's = """\nx\n""";\n')
        self.assertEqual(caught.exception.line, 1)


class TestRustCharacterLiterals(unittest.TestCase):
    RUST = PLAIN._replace(char_literal="rust")

    def test_lifetimes_do_not_open_a_character_literal(self):
        text = "fn f<'a>(x: &'a str) -> &'a str { x } // see ADR-9\n"
        self.assertEqual(found(self.RUST, text), [("C3", 1)])

    def test_a_label_does_not_open_a_character_literal(self):
        self.assertEqual(found(self.RUST, "'outer: loop {} // see ADR-9\n"), [("C3", 1)])

    def test_a_character_literal_holding_a_quote_is_content(self):
        self.assertEqual(comments(self.RUST, "let q = '\"'; // ok\n"), [["// ok"]])

    def test_escaped_character_literals_are_content(self):
        text = "let a = '\\''; let b = b'/'; let c = '\\u{1F600}'; let d = '\\x2F'; // see ADR-9\n"
        self.assertEqual(comments(self.RUST, text), [["// see ADR-9"]])

    def test_a_character_literal_holding_a_slash_is_content(self):
        self.assertEqual(comments(self.RUST, "let s = '/'; // ok\n"), [["// ok"]])


class TestLineContinuation(unittest.TestCase):
    CONTINUED = PLAIN._replace(line_continuation=True)

    def test_a_continued_line_comment_is_one_block(self):
        self.assertEqual(found(self.CONTINUED, "// one \\\n two\nint x;\n"), [("C1", 1)])

    def test_a_line_comment_does_not_continue_by_default(self):
        self.assertEqual(found(PLAIN, "// one \\\n two\nint x;\n"), [])

    def test_a_continued_trailing_comment_reads_its_next_line_as_comment(self):
        text = "int x; // one \\\n see ADR-9\nint y;\n"
        self.assertEqual(comments(self.CONTINUED, text), [["// one \\"], [" see ADR-9"], []])
        self.assertEqual(found(self.CONTINUED, text), [("C1", 1), ("C3", 2)])

    def test_space_after_the_backslash_still_continues(self):
        self.assertEqual(found(self.CONTINUED, "// one \\  \n two\nint x;\n"), [("C1", 1)])

    def test_a_continued_comment_joins_the_comment_lines_around_it(self):
        self.assertEqual(found(self.CONTINUED, "// one\n// \\\nthree\nint x;\n"), [("C1", 1)])

    def test_a_backslash_on_the_last_line_ends_the_text(self):
        self.assertEqual(found(self.CONTINUED, "int x; // see ADR-9 \\"), [("C3", 1)])


class TestWindowsLineEndings(unittest.TestCase):
    COMMON = ('/* a\n   b */ s = "*/";\nint x; // one \\\n two\nu = """\n// c\n""";\nv = "d\n// e";\n'
              '// f\n// g\n')
    RAW = {"backtick": "s = `\n// h\n`;\n", "rust": 's = r#"\n// h\n"#;\n', "swift": 's = #"""\n// h\n"""#\n',
           "cpp": 's = R"x(\n// h\n)x";\n'}

    def test_every_option_reads_crlf_and_cr_as_lf(self):
        for raw, string in self.RAW.items():
            syntax = clike.Syntax(True, True, raw, True, "rust", True)
            text = self.COMMON + string
            with self.subTest(raw=raw):
                expected = found(syntax, text)
                self.assertEqual(expected, [("C1", 1), ("C1", 3), ("C1", 10)])
                self.assertEqual(found(syntax, text.replace("\n", "\r\n")), expected)
                self.assertEqual(found(syntax, text.replace("\n", "\r")), expected)


if __name__ == "__main__":
    unittest.main()

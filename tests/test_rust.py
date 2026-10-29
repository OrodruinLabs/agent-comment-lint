"""Rust lexing: raw, byte and C strings and characters are content, lifetimes are not, and block comments nest."""
import os
import re
import unittest

from agent_comment_lint.lexers import LexError, family_for
from support import comments, found

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def lex(text):
    return family_for("a.rs").lex(text)


class TestScope(unittest.TestCase):
    def test_the_rust_extension_is_covered(self):
        self.assertEqual(family_for("src/lib.rs").name, "rust")
        self.assertEqual(found("a.rs", "// see ADR-9\n"), [("C3", 1)])

    def test_the_pre_commit_filter_matches_rust_files(self):
        with open(os.path.join(REPO, ".pre-commit-hooks.yaml"), encoding="utf-8") as handle:
            filters = re.findall(r"^\s*files: (.+)$", handle.read(), flags=re.M)
        self.assertEqual(len(filters), 2)
        self.assertEqual(filters[0], filters[1])
        self.assertTrue(re.search(filters[0], "src/lib.rs"))
        self.assertFalse(re.search(filters[0], "lib.rst"))


class TestCharactersAndLifetimes(unittest.TestCase):
    def test_lifetimes_do_not_open_a_character_literal(self):
        self.assertEqual(found("a.rs", "fn f<'a>(x: &'a str) -> &'a str { x } // see ADR-9\n"), [("C3", 1)])

    def test_a_character_literal_holding_a_quote_is_content(self):
        self.assertEqual(found("a.rs", "let q = '\"'; // ok\n"), [])
        self.assertEqual(comments("a.rs", "let q = '\"'; // ok\n"), [["// ok"]])

    def test_lifetimes_and_labels_are_not_characters(self):
        for code in ("let s: &'static str = x;", "let s: &'_ str = x;", "'outer: loop {}",
                     "impl<'a> T for S<'a> {}", "fn f<T>() where T: 'a {}", "let v: Vec<'a> = x;"):
            with self.subTest(code=code):
                self.assertEqual(found("a.rs", code + " // see ADR-9\n"), [("C3", 1)])

    def test_escaped_characters_are_content(self):
        for code in (r"let c = '\u{1F600}';", r"let c = '\x7f';", r"let c = '\'';", r"let c = '\\';",
                     "let c = b'\"';", r"let c = b'\'';", "let c = '\"';"):
            with self.subTest(code=code):
                self.assertEqual(found("a.rs", code + " // see ADR-9\n"), [("C3", 1)])

    def test_a_quote_in_a_doc_comment_is_prose(self):
        self.assertEqual(found("a.rs", "/// it's fine\nfn f() {}\n"), [])


class TestStrings(unittest.TestCase):
    def test_a_raw_string_with_a_hash_quote_is_content(self):
        self.assertEqual(found("a.rs", 'let s = r##"a "# ADR-9"##;\n'), [])

    def test_a_plain_string_may_cross_lines(self):
        self.assertEqual(found("a.rs", 'let s = "a\n// ADR-9\n";\n'), [])

    def test_an_unterminated_raw_string_cannot_be_lexed(self):
        with self.assertRaises(LexError):
            lex('let s = r#"x\n')

    def test_prefixed_strings_are_content(self):
        for code in ('let s = b"// x";', 'let s = c"// x";', 'let s = br#"// x"#;', 'let s = cr"// x";',
                     'let s = r"// x";', 'let s = br"// x";'):
            with self.subTest(code=code):
                self.assertEqual(found("a.rs", code + " // see ADR-9\n"), [("C3", 1)])

    def test_backslashes_end_raw_strings_not_escape_them(self):
        self.assertEqual(found("a.rs", 'let s = r"\\"; // see ADR-9\n'), [("C3", 1)])
        self.assertEqual(found("a.rs", 'let s = r#"\\"#; // see ADR-9\n'), [("C3", 1)])
        self.assertEqual(found("a.rs", 'let s = "\\\\"; // see ADR-9\n'), [("C3", 1)])

    def test_macro_strings_are_content(self):
        self.assertEqual(found("a.rs", 'println!("// {}", x); // see ADR-9\n'), [("C3", 1)])
        self.assertEqual(found("a.rs", 'format!(r#"{}"#, y); // see ADR-9\n'), [("C3", 1)])

    def test_an_unterminated_byte_string_cannot_be_lexed(self):
        with self.assertRaises(LexError):
            lex('let s = b"x\n')


class TestComments(unittest.TestCase):
    def test_nested_block_comments_are_one_block(self):
        self.assertEqual(found("a.rs", "/* a /* b */ c\n d */\nfn f() {}\n"), [("C1", 1)])

    def test_a_nested_block_closing_mid_line_leaves_the_rest_as_code(self):
        self.assertEqual(found("a.rs", "/* a /* b */ still comment */ // see ADR-9\n"), [("C3", 1)])
        self.assertEqual(found("a.rs", "/* a /* b\n */ c */ // see ADR-9\n"), [("C1", 1), ("C3", 2)])

    def test_an_unterminated_nested_block_cannot_be_lexed(self):
        with self.assertRaises(LexError):
            lex("/* a /* b */ c\nfn f() {}\n")

    def test_inner_doc_comments_are_comments(self):
        self.assertEqual(found("a.rs", "//! one\n//! two\n"), [("C1", 1)])

    def test_doc_comments_follow_the_same_rules(self):
        self.assertEqual(found("a.rs", "/// Adds.\n/// # Examples\nfn f() {}\n"), [("C1", 1)])
        self.assertEqual(found("a.rs", "/// Adds.\nfn f() {}\n"), [])
        self.assertEqual(found("a.rs", "/** Adds.\n * # Examples\n */\nfn f() {}\n"), [("C1", 1)])
        self.assertEqual(found("a.rs", "/*! Adds.\n * # Examples\n */\n"), [("C1", 1)])

    def test_attributes_and_shebangs_are_code(self):
        self.assertEqual(found("a.rs", '#[doc = "// x"]\n#![allow(dead_code)]\n'), [])
        self.assertEqual(found("a.rs", "#!/usr/bin/env rust-script\nfn main() {}\n"), [])

    def test_operators_are_not_comments(self):
        self.assertEqual(found("a.rs", "let f = |x| x / 2; // see ADR-9\n"), [("C3", 1)])
        self.assertEqual(found("a.rs", "let y = x as f32 / 2.0; // see ADR-9\n"), [("C3", 1)])
        self.assertEqual(found("a.rs", "let v = Vec::<u8>::new(); // see ADR-9\n"), [("C3", 1)])

    def test_crlf_behaves_like_lf(self):
        text = "/* a /* b */ c */ // see ADR-9\r\nlet s = r#\"// x\"#;\r\n/// Adds.\r\n/// # Examples\r\nfn f() {}\r\n"
        self.assertEqual(found("a.rs", text), found("a.rs", text.replace("\r\n", "\n")))
        self.assertEqual(found("a.rs", text), [("C3", 1), ("C1", 3)])


if __name__ == "__main__":
    unittest.main()

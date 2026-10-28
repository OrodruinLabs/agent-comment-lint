"""C1 counts only lines that hold a letter or digit, in any script: rulers and other decoration are not prose."""
import unittest

from agent_comment_lint import engine
from support import found


def spans(path, text):
    """(rule, line, end_line, message) for every finding in `text`, read as the language `path` names."""
    return [(f.rule, f.line, f.end_line, f.message) for f in engine.check_text(path, text).findings]


class TestDecorationIsNotProse(unittest.TestCase):
    def test_a_title_between_two_rulers_is_one_line_of_prose(self):
        for ruler in ("// ------", "// " + "-" * 75, "// ═══════", "//////"):
            with self.subTest(ruler=ruler):
                self.assertEqual(found("a.ts", "%s\n// Title\n%s\nconst a = 1;\n" % (ruler, ruler)), [])

    def test_a_lone_divider_is_not_prose(self):
        self.assertEqual(found("a.ts", "// -----\nconst a = 1;\n"), [])

    def test_a_title_framed_inside_its_ruler_is_one_line_of_prose(self):
        self.assertEqual(found("a.ts", "// ===== Section =====\nconst a = 1;\n"), [])

    def test_hash_rulers_are_decoration_in_every_hash_language(self):
        for path, code in (("a.py", "x = 1\n"), ("a.sh", "x=1\n"), ("a.yml", "x: 1\n")):
            with self.subTest(path=path):
                self.assertEqual(found(path, "#####\n# Title\n#####\n" + code), [])

    def test_rulers_inside_a_block_comment_are_decoration(self):
        self.assertEqual(found("a.css", "/* ====\n   Title\n   ==== */\na { color: red; }\n"), [])
        self.assertEqual(found("a.ts", "/*\n * ----\n * Title\n * ----\n */\nconst a = 1;\n"), [])
        self.assertEqual(found("a.cs", "/*\n * ----\n * Title\n * ----\n */\nint x;\n"), [])

    def test_a_docstring_heading_underline_is_decoration(self):
        self.assertEqual(found("a.py", 'def f():\n    """\n    Title\n    -----\n    """\n'), [])

    def test_a_box_drawing_with_one_label_is_one_line_of_prose(self):
        self.assertEqual(found("a.ts", "// ┌───┐\n// │ A │\n// └───┘\nconst a = 1;\n"), [])

    def test_letterless_art_of_any_length_is_never_prose(self):
        self.assertEqual(found("a.ts", "// ~~~~ ~~~~\n" * 20 + "const a = 1;\n"), [])


class TestProseStillCounts(unittest.TestCase):
    def test_a_ruler_does_not_split_a_block(self):
        self.assertEqual(spans("a.ts", "// one\n// ----\n// two\nconst a = 1;\n"),
                         [("C1", 1, 3, "2-line prose block (limit 1)")])

    def test_prose_under_a_banner_counts_with_its_title(self):
        self.assertEqual(spans("a.ts", "// ---\n// Title\n// ---\n// more\nconst a = 1;\n"),
                         [("C1", 2, 4, "2-line prose block (limit 1)")])

    def test_two_framed_titles_are_two_lines_of_prose(self):
        self.assertEqual(found("a.ts", "// ===== A =====\n// ===== B =====\nconst a = 1;\n"), [("C1", 1)])

    def test_a_block_is_reported_over_its_prose_lines_only(self):
        text = "/* ====\n   One\n   Two\n   ==== */\na { color: red; }\n"
        self.assertEqual(spans("a.css", text), [("C1", 2, 3, "2-line prose block (limit 1)")])

    def test_a_box_drawing_with_two_labels_is_two_lines_of_prose(self):
        text = "// ┌───┐\n// │ A │\n// │ B │\n// └───┘\nconst a = 1;\n"
        self.assertEqual(spans("a.ts", text), [("C1", 2, 3, "2-line prose block (limit 1)")])

    def test_a_digit_or_a_letter_makes_a_line_prose(self):
        self.assertEqual(found("a.ts", "// 1.\n// -> x\nconst a = 1;\n"), [("C1", 1)])

    def test_a_line_of_symbols_alone_is_not_prose(self):
        self.assertEqual(found("a.ts", "// ->\n// x\nconst a = 1;\n"), [])

    def test_prose_in_any_script_counts(self):
        for text in ("// 日本語\n// 日本語\n", "// ¿Qué pasó?\n// Sí\n", "// Привет\n// мир\n"):
            with self.subTest(text=text):
                self.assertEqual(found("a.ts", text + "const a = 1;\n"), [("C1", 1)])

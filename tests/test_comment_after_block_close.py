"""What follows a closing `*/` on its line is read as a line of its own, so a comment there is scored."""
import unittest

from agent_comment_lint import engine
from support import found

CLOSE_THEN_COMMENT = "/* one\n*/ // two\n// three\n"
LINE_AT_A_TIME = ("a.cs", "main.tf")


class TestLexerPlacedBlocks(unittest.TestCase):
    def test_a_comment_after_the_close_starts_the_next_block(self):
        for path in ("a.ts", "a.tsx", "a.js", "a.mjs"):
            self.assertEqual(found(path, CLOSE_THEN_COMMENT), [("C1", 2)], path)

    def test_the_block_is_the_one_the_same_two_lines_make_alone(self):
        alone = engine.check_text("a.ts", "\n// two\n// three\n").findings
        self.assertEqual(engine.check_text("a.ts", CLOSE_THEN_COMMENT).findings, alone)
        self.assertEqual([(finding.line, finding.end_line) for finding in alone], [(2, 3)])

    def test_no_space_is_needed_after_the_close(self):
        self.assertEqual(found("a.ts", "/* one\n*/// two\n// three\n"), [("C1", 2)])

    def test_the_closed_block_and_the_comment_after_it_are_two_blocks(self):
        self.assertEqual(found("a.ts", "/* one\n*/ // two\nlet a = 1;\n"), [])

    def test_a_comment_that_trails_code_after_the_close_is_not_a_comment_line(self):
        self.assertEqual(found("a.ts", "/* one\n*/ run(); // two\n// three\n"), [])

    def test_a_one_line_block_after_the_close_still_passes(self):
        self.assertEqual(found("a.ts", "/* one\n*/ /* two */\n/* three */\n"), [])

    def test_a_one_line_block_between_the_close_and_a_comment_makes_it_a_trailing_comment(self):
        self.assertEqual(found("a.ts", "/* one\n*/ /* a */ // two\n// three\n"), [])

    def test_a_block_that_opens_after_the_close_is_counted_once(self):
        self.assertEqual(found("a.ts", "/* one\n*/ /* two\nthree */\n"), [("C1", 2)])

    def test_two_slashes_after_a_close_are_no_comment_in_a_stylesheet(self):
        self.assertEqual(found("a.css", "/* one\n*/ // two\n// three\n"), [])


class TestLineAtATimeBlocks(unittest.TestCase):
    def assert_matches_ts(self, text, expected):
        """C# and HCL give the verdict TypeScript gives, and it is `expected`."""
        for path in LINE_AT_A_TIME:
            self.assertEqual(found(path, text), found("a.ts", text), path)
            self.assertEqual(found(path, text), expected, path)

    def test_a_comment_after_the_close_starts_the_next_block(self):
        for path in LINE_AT_A_TIME:
            self.assertEqual(found(path, CLOSE_THEN_COMMENT), [("C1", 2)], path)

    def test_a_hash_comment_after_the_close_starts_the_next_block(self):
        self.assertEqual(found("main.tf", "/* one\n*/ # two\n# three\n"), [("C1", 2)])

    def test_the_closed_block_and_the_comment_after_it_are_two_blocks(self):
        self.assertEqual(found("a.cs", "/* one\n*/ // two\nint x;\n"), [])

    def test_code_after_the_close_is_not_a_comment_line(self):
        self.assertEqual(found("a.cs", "/* one\n*/ int x; // two\n// three\n"), [])

    def test_a_block_that_opens_after_the_close_is_scored_as_in_the_lexed_languages(self):
        self.assert_matches_ts("/* one\n*/ /* two\nthree */\n", [("C1", 2)])

    def test_a_comment_after_the_close_of_a_block_that_opened_after_code_starts_the_next_block(self):
        self.assert_matches_ts("int x = 1; /* note\n*/ // two\n// three\n", [("C1", 2)])

    def test_the_same_holds_when_the_close_ends_a_line_of_prose(self):
        for path in LINE_AT_A_TIME:
            self.assertEqual(found(path, "int x = 1; /* note\nmore */ // two\n// three\n"), [("C1", 2)], path)

    def test_a_comment_after_a_star_line_that_closes_a_block_opened_after_code_is_not_counted_twice(self):
        for path in LINE_AT_A_TIME:
            self.assertEqual(found(path, "int x = 1; /* note\n * more */ // two\nint y;\n"), [], path)

    def test_a_comment_after_a_comment_line_that_closes_a_block_opened_after_code_is_not_counted_twice(self):
        for path in LINE_AT_A_TIME:
            self.assertEqual(found(path, "int x = 1; /* note\n// more */ // two\nint y;\n"), [], path)
        self.assertEqual(found("main.tf", "x = 1 /* note\n# more */ # two\ny = 2\n"), [])

    def test_star_lines_of_a_block_opened_after_code_still_join_the_comment_below_it(self):
        for path in LINE_AT_A_TIME:
            self.assertEqual(found(path, "int x = 1; /* note\n * more */\n// two\n"), [("C1", 2)], path)

    def test_code_after_the_close_of_a_block_that_opened_after_code_is_not_a_comment_line(self):
        self.assertEqual(found("a.cs", "int x = 1; /* note\n*/ int y; // two\n// three\n"), [])

    def test_code_that_starts_with_a_star_after_the_close_is_not_a_comment_line(self):
        self.assert_matches_ts("/* set\n*/ *p = 1;\n// next\n", [])

    def test_a_star_line_inside_a_block_still_continues_it(self):
        self.assertEqual(found("a.cs", "/* one\n * two\n */ *p = 1;\n"), [("C1", 1)])


class TestDocstrings(unittest.TestCase):
    def test_the_line_that_closes_a_docstring_has_no_block_close_to_read_past(self):
        self.assertEqual(found("a.py", '"# one"\n# two\n'), [])

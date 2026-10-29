"""The governance list: a fixed core, opt-in packs, and a repository's own additions, which can only add."""
import re
import unittest

from agent_comment_lint import governance
from agent_comment_lint.governance import first_reference
from support import found


class TestCore(unittest.TestCase):
    def assert_flagged(self, comment, reference):
        self.assertEqual(first_reference(comment), reference, comment)

    def test_decision_and_planning_ids_are_flagged(self):
        for comment, reference in (("see ADR-0009", "ADR-0009"), ("per PRD-1", "PRD-1"), ("TRD-12b says", "TRD-12b"),
                                   ("see FEAT-AUTH", "FEAT-AUTH"), ("DEF-3 again", "DEF-3"),
                                   ("PATCH-2 moved it", "PATCH-2"), ("TASK-12 is open", "TASK-12"),
                                   ("TC-4 covers it", "TC-4"), ("see the test-plan", "test-plan")):
            self.assert_flagged(comment, reference)

    def test_acceptance_criterion_ids_are_flagged(self):
        self.assert_flagged("AC5 names the exclusions", "AC5")
        self.assert_flagged("per AC-F5.6 the code is never null", "AC-F5.6")

    def test_work_items_and_pull_requests_are_flagged(self):
        self.assert_flagged("see work item 1234", "work item 1234")
        self.assert_flagged("Story 716 pinned the seed shape", "Story 716")
        self.assert_flagged("fixed in bug #42", "bug #42")
        self.assert_flagged("raised in PR 519", "PR 519")
        self.assert_flagged("as thread 4821 asked", "thread 4821")

    def test_documents_and_instruction_files_are_flagged(self):
        self.assert_flagged("see docs/design/auth.md", "docs/design/auth.md")
        self.assert_flagged("as CLAUDE.md says", "CLAUDE.md")
        self.assert_flagged("as AGENTS.md says", "AGENTS.md")

    def test_a_reference_is_reported_through_the_engine(self):
        self.assertEqual(found("a.ts", "// see ADR-0009\n"), [("C3", 1)])
        self.assertEqual(found("a.py", "# see work item 1234\n"), [("C3", 1)])

    def test_pack_shapes_are_not_in_the_core(self):
        for comment in ("see AB#4321", "ADO #795", "per D-7", "per D7 we chose", "tracked as WEB-T022"):
            self.assertIsNone(first_reference(comment), comment)


class TestNearMisses(unittest.TestCase):
    def test_names_that_share_a_shape_with_an_id_are_not_flagged(self):
        for comment in ("hashed with SHA-256", "encrypted with AES-256", "an RFC-7807 problem", "UTF-16 text",
                        "an ISO-8601 date", "transcript code RA-150", "PI-270 opens the case", "TC 971 / AC 501",
                        "the X-B3 header", "RSA-2048 key", "the adr-0009 folder slug"):
            self.assertIsNone(first_reference(comment), comment)

    def test_a_bare_number_is_not_a_work_item(self):
        for comment in ("Fixes #3425 in the override path", "the fallback is #002FD9, not #1A4DFF",
                        "renders as &#9888; here", "retry the task 100 times", "answers issue 404 with a page",
                        "a 3-story building", "bug 500 is not a reference", "story 12 of the building"):
            self.assertIsNone(first_reference(comment), comment)


class TestPacks(unittest.TestCase):
    def test_azure_boards_flags_work_item_links(self):
        boards = governance.matcher(packs=("azure-boards",))
        self.assertEqual(first_reference("see AB#4321 for the epic", boards), "AB#4321")
        self.assertEqual(first_reference("two roles (ADO #795)", boards), "ADO #795")

    def test_decision_ids_flag_short_decision_names(self):
        decisions = governance.matcher(packs=("decision-ids",))
        for comment, reference in (("per D-7", "D-7"), ("see D-12b", "D-12b"), ("per D7 we chose", "D7")):
            self.assertEqual(first_reference(comment, decisions), reference, comment)

    def test_decision_ids_leave_a_hex_byte_run_alone(self):
        decisions = governance.matcher(packs=("decision-ids",))
        self.assertIsNone(first_reference("bytes 0A D3 FF", decisions))

    def test_task_ids_flag_a_prefixed_class_letter_and_number(self):
        tasks = governance.matcher(packs=("task-ids",))
        for comment, reference in (("tracked as WEB-T022", "WEB-T022"), ("see AUTH-F053", "AUTH-F053"),
                                   ("DATA-P002a moved it", "DATA-P002a")):
            self.assertEqual(first_reference(comment, tasks), reference, comment)

    def test_a_pack_keeps_the_core(self):
        self.assertEqual(first_reference("see ADR-1", governance.matcher(packs=("task-ids",))), "ADR-1")

    def test_an_unknown_pack_is_refused(self):
        with self.assertRaises(KeyError):
            governance.matcher(packs=("jira",))


class TestExtras(unittest.TestCase):
    def extra(self, pattern):
        return governance.Extra(pattern, "why", re.compile(pattern))

    def test_an_extra_pattern_adds_a_reference(self):
        tickets = governance.matcher(extras=(self.extra(r"\bWEB-\d+"),))
        self.assertEqual(first_reference("fixed in WEB-12", tickets), "WEB-12")

    def test_the_leftmost_reference_wins_across_core_and_extras(self):
        tickets = governance.matcher(extras=(self.extra(r"\bWEB-\d+"),))
        self.assertEqual(first_reference("WEB-12 and ADR-3", tickets), "WEB-12")
        self.assertEqual(first_reference("ADR-3 and WEB-12", tickets), "ADR-3")

    def test_an_extra_keeps_its_own_inline_flags(self):
        tickets = governance.matcher(extras=(self.extra(r"(?i)\bweb-\d+"),))
        self.assertEqual(first_reference("fixed in Web-12", tickets), "Web-12")


class TestAgentContextPack(unittest.TestCase):
    pack = governance.matcher(("agent-context",))

    def test_plan_and_chat_references_are_flagged(self):
        for comment, reference in (("now reads useDataTypes() itself (Task 8)", "Task 8"),
                                   ("The user asked for it gone.", "The user asked"),
                                   ("See INTERNAL_NOTES.md section 4", "INTERNAL_NOTES.md"),
                                   ("Step 3 of the plan", "Step 3 of the plan"),
                                   ("as discussed, retry twice", "as discussed"),
                                   ("per the code review", "per the code review"),
                                   ("tracked in PLAN.md", "PLAN.md")):
            self.assertEqual(self.pack.first_reference(comment), reference, comment)

    def test_a_work_item_with_a_hash_is_already_core(self):
        self.assertEqual(first_reference("(Task #1775)"), "Task #1775")

    def test_ordinary_text_and_well_known_files_are_not_flagged(self):
        # A moved-to note is out-of-scope edit narration, which the spec leaves to the model, not to C3.
        for comment in ("(moved to ./phaseStepper.ts)", "see README.md", "per CHANGELOG.md", "task 8 ran twice",
                        "A.md is one letter", "Taskbar 8"):
            self.assertIsNone(self.pack.first_reference(comment), comment)

    def test_the_pack_is_off_unless_named(self):
        self.assertIsNone(first_reference("now reads it itself (Task 8)"))

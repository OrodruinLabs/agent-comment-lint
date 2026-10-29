"""The per-agent adapters: each turns one agent's hook event into the writes the hook judges."""
import json
import os
import unittest

from agent_comment_lint import hook

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "agents")
CLAUDE_WRITE = {"tool_name": "Write", "tool_input": {"file_path": "a.ts", "content": "const a = 1;\n"}}


def fixture(name):
    with open(os.path.join(FIXTURES, name + ".json"), encoding="utf-8") as handle:
        return json.load(handle)


class AdapterContract:
    """Mixin for an agent's test class: sets `agent`, `write_fixture`, `non_write_fixture`, `pathless_fixture`."""

    agent = write_fixture = non_write_fixture = pathless_fixture = None

    def test_the_write_fixture_yields_a_target(self):
        self.assertGreaterEqual(len(hook.targets(fixture(self.write_fixture), self.agent)), 1)

    def test_the_non_write_fixture_yields_nothing(self):
        self.assertEqual(hook.targets(fixture(self.non_write_fixture), self.agent), [])

    def test_the_pathless_fixture_is_refused(self):
        with self.assertRaises(hook.HookInputError):
            hook.targets(fixture(self.pathless_fixture), self.agent)


class TestClaudeAdapter(unittest.TestCase):
    def test_the_claude_adapter_is_the_default(self):
        self.assertEqual(hook.targets(CLAUDE_WRITE, "claude"), [hook.target(CLAUDE_WRITE)])

    def test_a_tool_that_writes_nothing_yields_no_target(self):
        self.assertEqual(hook.targets({"tool_name": "Read", "tool_input": {}}, "claude"), [])

    def test_an_event_that_is_not_an_object_is_refused(self):
        with self.assertRaises(hook.HookInputError):
            hook.targets([], "claude")

    def test_a_target_applies_loosely_unless_told_otherwise(self):
        self.assertFalse(hook.target(CLAUDE_WRITE).must_apply)


class TestRegistry(unittest.TestCase):
    def test_every_adapter_has_a_title_and_no_title_is_orphaned(self):
        self.assertEqual(sorted(hook.TITLES), sorted(hook.ADAPTERS))

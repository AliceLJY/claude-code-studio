import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

# Claude Code 2.1.214 hook event names. Keeping this explicit makes changes to
# the example configuration require a deliberate compatibility check.
SUPPORTED_HOOK_EVENTS = {
    "ConfigChange",
    "Elicitation",
    "ElicitationResult",
    "InstructionsLoaded",
    "Notification",
    "PermissionRequest",
    "PostToolUse",
    "PostToolUseFailure",
    "PreCompact",
    "PreToolUse",
    "SessionEnd",
    "SessionStart",
    "Stop",
    "SubagentStart",
    "SubagentStop",
    "TaskCompleted",
    "TeammateIdle",
    "UserPromptSubmit",
    "WorktreeCreate",
    "WorktreeRemove",
}


class ExampleValidationTests(unittest.TestCase):
    def test_json_examples_parse(self):
        for path in sorted((ROOT / "examples").glob("*.json")):
            with self.subTest(path=path.name):
                json.loads(path.read_text(encoding="utf-8"))

    def test_hook_example_uses_supported_events(self):
        config = json.loads(
            (ROOT / "examples" / "hooks.json").read_text(encoding="utf-8")
        )
        events = set(config["hooks"])
        self.assertTrue(events)
        self.assertEqual(set(), events - SUPPORTED_HOOK_EVENTS)


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch

from studio import watcher


class WatcherTests(unittest.TestCase):
    def test_disabled_auto_kick_does_not_write_to_terminal(self):
        with (
            patch.object(watcher, "AUTO_KICK", False),
            patch.object(watcher.mux, "send_keys") as send_keys,
            patch.object(watcher.mux, "send_enter") as send_enter,
        ):
            kicked = watcher.kick_agent("agent-1")

        self.assertFalse(kicked)
        send_keys.assert_not_called()
        send_enter.assert_not_called()

    def test_try_kick_does_not_start_cooldown_when_disabled(self):
        kicked_at = {}
        with (
            patch.object(watcher, "AUTO_KICK", False),
            patch.object(watcher.mux, "list_panes", return_value={"agent-1"}),
            patch.object(watcher, "is_agent_idle", return_value=True),
        ):
            kicked = watcher._try_kick("agent-1", kicked_at, 30, "test")

        self.assertFalse(kicked)
        self.assertEqual(kicked_at, {})


if __name__ == "__main__":
    unittest.main()

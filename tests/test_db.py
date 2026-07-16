import tempfile
import time
import unittest
from pathlib import Path

from studio import db


class SQLiteBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="studio-db-test-")
        self.original_db_path = db.DB_PATH
        db.DB_PATH = str(Path(self.temp_dir.name) / "studio.db")
        db._broadcast_reads_ensured = False
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self.original_db_path
        db._broadcast_reads_ensured = False
        self.temp_dir.cleanup()

    def register(self, *agent_ids: str):
        for agent_id in agent_ids:
            db.register_agent(agent_id, agent_id)

    def test_broadcast_excludes_sender_and_reaches_recipient_once(self):
        self.register("commander", "agent-1")

        db.broadcast("commander", "hello")

        self.assertEqual(db.count_unread("commander"), 0)
        self.assertEqual(db.read_inbox("commander"), [])
        self.assertEqual(db.count_unread("agent-1"), 1)
        self.assertEqual([m["content"] for m in db.read_inbox("agent-1")], ["hello"])
        self.assertEqual(db.count_unread("agent-1"), 0)
        self.assertEqual(db.read_inbox("agent-1"), [])

    def test_broadcast_read_state_is_per_recipient(self):
        self.register("commander", "agent-1", "agent-2")
        db.broadcast("commander", "shared")

        db.read_inbox("agent-1")

        self.assertEqual(db.count_unread("agent-1"), 0)
        self.assertEqual(db.count_unread("agent-2"), 1)

    def test_new_agent_does_not_receive_historical_broadcast(self):
        self.register("commander")
        db.broadcast("commander", "before registration")
        time.sleep(0.001)
        self.register("late-agent")

        self.assertEqual(db.count_unread("late-agent"), 0)
        self.assertEqual(db.read_inbox("late-agent", unread_only=False), [])

    def test_direct_message_behavior_is_unchanged(self):
        self.register("commander", "agent-1")
        db.send_message("commander", "agent-1", "direct")

        self.assertEqual(db.count_unread("agent-1"), 1)
        messages = db.read_inbox("agent-1")
        self.assertEqual(messages[0]["to_agent"], "agent-1")
        self.assertEqual(db.count_unread("agent-1"), 0)


if __name__ == "__main__":
    unittest.main()

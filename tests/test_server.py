import unittest
from unittest.mock import patch

from studio import server


class ServerTests(unittest.TestCase):
    def test_reserved_broadcast_id_cannot_register(self):
        with patch.object(server.db, "register_agent") as register_agent:
            result = server.register("__broadcast__", "Reserved")

        self.assertIn("reserved", result)
        register_agent.assert_not_called()

    def test_self_assigned_task_does_not_claim_notification(self):
        task = {
            "id": 1,
            "title": "task",
            "assigned_to": "agent-1",
            "assigned_by": "agent-1",
        }
        with (
            patch.object(server.db, "get_tasks", return_value=[task]),
            patch.object(server.db, "update_task", return_value=True),
            patch.object(server.db, "send_message") as send_message,
        ):
            result = server.update_task(1, "done")

        self.assertNotIn("Notified", result)
        send_message.assert_not_called()

    def test_dispatcher_is_notified_when_different_from_assignee(self):
        task = {
            "id": 1,
            "title": "task",
            "assigned_to": "agent-1",
            "assigned_by": "commander",
        }
        with (
            patch.object(server.db, "get_tasks", return_value=[task]),
            patch.object(server.db, "update_task", return_value=True),
            patch.object(server.db, "send_message") as send_message,
        ):
            result = server.update_task(1, "done", "finished")

        self.assertIn("Notified 'commander'", result)
        send_message.assert_called_once()

    def test_loopback_detection(self):
        for host in ("localhost", "127.0.0.1", "127.12.0.4", "::1", "[::1]"):
            with self.subTest(host=host):
                self.assertTrue(server._is_loopback_host(host))
        for host in ("0.0.0.0", "192.168.1.10", "studio.example.test"):
            with self.subTest(host=host):
                self.assertFalse(server._is_loopback_host(host))


if __name__ == "__main__":
    unittest.main()

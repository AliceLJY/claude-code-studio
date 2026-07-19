import unittest
from unittest.mock import MagicMock, patch

import redis

from studio import db_redis


class RedisBackendTests(unittest.TestCase):
    def test_init_db_fails_fast_without_logging_credential_url(self):
        error = redis.ConnectionError("connection refused")
        with (
            patch.object(
                db_redis, "REDIS_URL", "redis://user:secret@example.test:6379"
            ),
            patch.object(db_redis, "get_conn", side_effect=error),
            patch.object(db_redis, "_reset_pool"),
            self.assertLogs(db_redis.logger, level="ERROR") as logs,
            self.assertRaises(redis.ConnectionError),
        ):
            db_redis.init_db()

        self.assertNotIn("secret", "\n".join(logs.output))

    def test_create_task_updates_hash_ttl_and_index_atomically(self):
        connection = MagicMock()
        connection.incr.return_value = 7
        pipeline = connection.pipeline.return_value

        with patch.object(db_redis, "get_conn", return_value=connection):
            task_id = db_redis.create_task(
                "title", "description", "agent-1", "commander"
            )

        self.assertEqual(task_id, 7)
        pipeline.hset.assert_called_once()
        pipeline.expire.assert_called_once_with("studio:task:7", db_redis.TASK_TTL)
        pipeline.rpush.assert_called_once_with("studio:tasks", 7)
        pipeline.execute.assert_called_once_with()

    def test_update_task_refreshes_ttl(self):
        connection = MagicMock()
        connection.exists.return_value = True
        pipeline = connection.pipeline.return_value

        with patch.object(db_redis, "get_conn", return_value=connection):
            updated = db_redis.update_task(3, status="done")

        self.assertTrue(updated)
        pipeline.hset.assert_called_once()
        pipeline.expire.assert_called_once_with("studio:task:3", db_redis.TASK_TTL)
        pipeline.execute.assert_called_once_with()

    def test_read_inbox_prunes_expired_message_ids(self):
        connection = MagicMock()
        connection.lrange.return_value = ["expired", "2"]
        connection.smembers.return_value = set()
        connection.hgetall.side_effect = [
            {},
            {
                "id": "2",
                "from_agent": "commander",
                "to_agent": "agent-1",
                "content": "live",
                "created_at": "1.0",
                "read": "0",
            },
        ]
        pipeline = connection.pipeline.return_value

        with patch.object(db_redis, "get_conn", return_value=connection):
            messages = db_redis.read_inbox("agent-1")

        self.assertEqual([message["content"] for message in messages], ["live"])
        pipeline.lrem.assert_any_call("studio:inbox:agent-1", 0, "expired")
        pipeline.lrem.assert_any_call("studio:inbox:agent-1", 1, "2")
        pipeline.execute.assert_called_once_with()

    def test_count_unread_ignores_history_and_prunes_expired_ids(self):
        connection = MagicMock()
        connection.lrange.return_value = ["direct-read", "broadcast-read", "direct-new", "expired"]
        connection.smembers.return_value = {"broadcast-read"}
        connection.hgetall.side_effect = [
            {"to_agent": "agent-1", "read": "1"},
            {"to_agent": "__broadcast__", "read": "0"},
            {"to_agent": "agent-1", "read": "0"},
            {},
        ]
        pipeline = connection.pipeline.return_value

        unread = db_redis.count_unread("agent-1", connection=connection)

        self.assertEqual(unread, 1)
        pipeline.lrem.assert_called_once_with("studio:inbox:agent-1", 0, "expired")
        pipeline.execute.assert_called_once_with()

    def test_get_tasks_prunes_expired_task_ids(self):
        connection = MagicMock()
        connection.lrange.return_value = ["expired", "3"]
        connection.hgetall.side_effect = [
            {},
            {
                "id": "3",
                "title": "live",
                "description": "",
                "assigned_to": "agent-1",
                "assigned_by": "commander",
                "priority": "medium",
                "status": "pending",
                "notes": "",
                "created_at": "1.0",
                "updated_at": "1.0",
            },
        ]
        pipeline = connection.pipeline.return_value

        with patch.object(db_redis, "get_conn", return_value=connection):
            tasks = db_redis.get_tasks()

        self.assertEqual([task["title"] for task in tasks], ["live"])
        pipeline.lrem.assert_called_once_with("studio:tasks", 0, "expired")
        pipeline.execute.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()

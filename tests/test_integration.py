import json
import os
import pty
import shutil
import subprocess
import tempfile
import time
import unittest
import uuid
from pathlib import Path

from studio import db_redis, mux


def _enabled(name: str) -> bool:
    return os.environ.get(name) == "1"


def _read_available_pty(fd: int) -> str:
    os.set_blocking(fd, False)
    chunks = []
    while True:
        try:
            chunk = os.read(fd, 65536)
        except (BlockingIOError, OSError):
            break
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks).decode(errors="replace")


@unittest.skipUnless(
    _enabled("STUDIO_REDIS_INTEGRATION"),
    "set STUDIO_REDIS_INTEGRATION=1 to exercise a live Redis server",
)
class RedisIntegrationTests(unittest.TestCase):
    def test_live_message_and_task_round_trip(self):
        old_url = db_redis.REDIS_URL
        old_prefix = db_redis.REDIS_PREFIX
        prefix = f"studio:test:{uuid.uuid4().hex}:"
        db_redis.REDIS_URL = os.environ.get(
            "STUDIO_REDIS_URL", "redis://127.0.0.1:6379"
        )
        db_redis.REDIS_PREFIX = prefix
        db_redis._reset_pool()

        try:
            db_redis.init_db()
            db_redis.register_agent("commander", "Commander", "orchestrator")
            db_redis.register_agent("agent-1", "Agent One", "worker")
            db_redis.register_agent("agent-2", "Agent Two", "worker")

            self.assertEqual(
                [agent["agent_id"] for agent in db_redis.list_agents()],
                ["agent-1", "agent-2", "commander"],
            )

            db_redis.send_message("commander", "agent-1", "direct")
            self.assertEqual(
                [message["content"] for message in db_redis.read_inbox("agent-1")],
                ["direct"],
            )
            self.assertEqual(db_redis.read_inbox("agent-1"), [])

            db_redis.broadcast("commander", "broadcast")
            self.assertEqual(
                [message["content"] for message in db_redis.read_inbox("agent-1")],
                ["broadcast"],
            )
            self.assertEqual(
                [message["content"] for message in db_redis.read_inbox("agent-2")],
                ["broadcast"],
            )

            task_id = db_redis.create_task(
                "live Redis",
                "exercise the real backend",
                "agent-1",
                "commander",
                "high",
            )
            self.assertTrue(
                db_redis.update_task(task_id, status="done", notes="verified")
            )
            tasks = db_redis.get_tasks(agent_id="agent-1", status="done")
            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0]["title"], "live Redis")
            self.assertEqual(tasks[0]["notes"], "verified")
        finally:
            connection = db_redis.get_conn()
            keys = list(connection.scan_iter(f"{prefix}*"))
            if keys:
                connection.delete(*keys)
            db_redis._reset_pool()
            db_redis.REDIS_URL = old_url
            db_redis.REDIS_PREFIX = old_prefix


@unittest.skipUnless(
    _enabled("STUDIO_ZELLIJ_INTEGRATION"),
    "set STUDIO_ZELLIJ_INTEGRATION=1 to exercise a live Zellij session",
)
class ZellijIntegrationTests(unittest.TestCase):
    def test_live_pane_write_enter_and_capture(self):
        import fcntl
        import struct
        import termios

        zellij = shutil.which("zellij")
        self.assertIsNotNone(zellij, "zellij must be available on PATH")

        old_mux = mux._mux
        old_session = mux.SESSION
        old_pane_map = mux.PANE_MAP_FILE
        old_config_dir = os.environ.get("ZELLIJ_CONFIG_DIR")
        old_term = os.environ.get("TERM")
        # Zellij 0.44.3 rejects longer generated names with a misleading
        # "session name must be less than 0 characters" validation error.
        session = f"st-{uuid.uuid4().hex[:10]}"
        process = None
        master_fd = None

        with tempfile.TemporaryDirectory(prefix="studio-zellij-") as temp_dir:
            temp_path = Path(temp_dir)
            config_path = temp_path / "config.kdl"
            config = subprocess.run(
                [zellij, "setup", "--dump-config"],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
            config_path.write_text(config.stdout, encoding="utf-8")
            pane_map_path = temp_path / "panes.json"

            try:
                os.environ["ZELLIJ_CONFIG_DIR"] = temp_dir
                os.environ["TERM"] = "xterm-256color"
                mux._mux = "zellij"
                mux.SESSION = session
                mux.PANE_MAP_FILE = str(pane_map_path)

                master_fd, slave_fd = pty.openpty()
                fcntl.ioctl(
                    slave_fd,
                    termios.TIOCSWINSZ,
                    struct.pack("HHHH", 24, 80, 0, 0),
                )
                env = os.environ.copy()
                env["TERM"] = "xterm-256color"
                process = subprocess.Popen(
                    [zellij, "--config", str(config_path), "-s", session],
                    cwd=temp_dir,
                    env=env,
                    stdin=slave_fd,
                    stdout=slave_fd,
                    stderr=slave_fd,
                    close_fds=True,
                    start_new_session=True,
                )
                os.close(slave_fd)
                time.sleep(0.5)

                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    result = subprocess.run(
                        [zellij, "list-sessions", "-n", "-s"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                        check=False,
                    )
                    if session in result.stdout.splitlines():
                        break
                    if process.poll() is not None:
                        output = _read_available_pty(master_fd)
                        self.fail(
                            "zellij exited before creating the test session "
                            f"(binary={zellij}, rc={process.returncode}, "
                            f"probe={result.stderr.strip()!r}): {output[-2000:]}"
                        )
                    time.sleep(0.2)
                else:
                    self.fail("zellij test session did not become ready")

                result = subprocess.run(
                    [
                        zellij,
                        "--session",
                        session,
                        "action",
                        "list-panes",
                        "--json",
                        "-a",
                        "-s",
                        "-t",
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                panes = json.loads(result.stdout)
                terminal_pane = next(pane for pane in panes if not pane["is_plugin"])
                pane_map_path.write_text(
                    json.dumps({"agent-1": str(terminal_pane["id"])}),
                    encoding="utf-8",
                )

                self.assertEqual(mux.list_panes(), {"agent-1"})
                marker = f"STUDIO_ZELLIJ_{uuid.uuid4().hex}"
                mux.send_keys("agent-1", f"printf '{marker}\\n'")
                mux.send_enter("agent-1")

                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if marker in mux.capture_pane("agent-1"):
                        break
                    time.sleep(0.2)
                else:
                    self.fail("marker did not appear in the live Zellij pane")
            finally:
                subprocess.run(
                    [zellij, "kill-session", session],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                if process is not None:
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
                if master_fd is not None:
                    os.close(master_fd)
                mux._mux = old_mux
                mux.SESSION = old_session
                mux.PANE_MAP_FILE = old_pane_map
                if old_config_dir is None:
                    os.environ.pop("ZELLIJ_CONFIG_DIR", None)
                else:
                    os.environ["ZELLIJ_CONFIG_DIR"] = old_config_dir
                if old_term is None:
                    os.environ.pop("TERM", None)
                else:
                    os.environ["TERM"] = old_term


if __name__ == "__main__":
    unittest.main()

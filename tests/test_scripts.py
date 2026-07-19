import os
import socket
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ScriptValidationTests(unittest.TestCase):
    def run_script(self, script: str, *args: str, **env_overrides: str):
        env = os.environ.copy()
        for key in (
            "STUDIO_BACKEND",
            "STUDIO_HOST",
            "STUDIO_MUX",
            "STUDIO_PORT",
            "STUDIO_STATE_DIR",
            "STUDIO_UNSAFE_REMOTE_MCP",
        ):
            env.pop(key, None)
        env.update(env_overrides)
        return subprocess.run(
            ["bash", str(ROOT / "scripts" / script), *args],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

    def test_launch_rejects_invalid_agent_count_before_starting_services(self):
        result = self.run_script("launch.sh", "0")
        self.assertEqual(result.returncode, 2)
        self.assertIn("positive integer", result.stderr)

    def test_launch_rejects_invalid_backend(self):
        result = self.run_script("launch.sh", "1", STUDIO_BACKEND="redsi")
        self.assertEqual(result.returncode, 2)
        self.assertIn("STUDIO_BACKEND", result.stderr)

    def test_launch_rejects_invalid_mux(self):
        result = self.run_script("launch.sh", "1", STUDIO_MUX="screen")
        self.assertEqual(result.returncode, 2)
        self.assertIn("STUDIO_MUX", result.stderr)

    def test_launch_rejects_invalid_port(self):
        result = self.run_script("launch.sh", "1", STUDIO_PORT="70000")
        self.assertEqual(result.returncode, 2)
        self.assertIn("STUDIO_PORT", result.stderr)

    def test_launch_rejects_remote_unauthenticated_bind(self):
        result = self.run_script("launch.sh", "1", STUDIO_HOST="0.0.0.0")
        self.assertEqual(result.returncode, 2)
        self.assertIn("refusing unauthenticated", result.stderr)

    def test_redis_preflight_does_not_echo_credential_url(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            free_port = str(sock.getsockname()[1])
        result = self.run_script(
            "launch.sh",
            "1",
            STUDIO_BACKEND="redis",
            STUDIO_PORT=free_port,
            STUDIO_REDIS_URL="redis://user:secret@127.0.0.1:1",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("configured Redis endpoint", result.stderr)
        self.assertNotIn("secret", result.stdout + result.stderr)

    def test_status_rejects_invalid_backend_before_importing_project(self):
        result = self.run_script("status.sh", STUDIO_BACKEND="redsi")
        self.assertEqual(result.returncode, 2)
        self.assertIn("STUDIO_BACKEND", result.stderr)

    def test_runtime_state_helper_creates_private_owned_directory(self):
        with tempfile.TemporaryDirectory(prefix="studio-runtime-test-") as parent:
            runtime_dir = str(Path(parent) / "runtime")
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    'source "$1"; STUDIO_STATE_DIR="$2"; studio_prepare_runtime_dir; printf "%s" "$STUDIO_RUNTIME_DIR"',
                    "bash",
                    str(ROOT / "scripts" / "runtime-state.sh"),
                    runtime_dir,
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, runtime_dir)
            self.assertEqual(stat.S_IMODE(os.stat(runtime_dir).st_mode), 0o700)

    def test_runtime_state_helper_rejects_symlink_directory(self):
        with tempfile.TemporaryDirectory(prefix="studio-runtime-link-") as parent:
            target = Path(parent) / "target"
            target.mkdir()
            runtime_link = Path(parent) / "runtime"
            runtime_link.symlink_to(target, target_is_directory=True)
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    'source "$1"; STUDIO_STATE_DIR="$2"; studio_prepare_runtime_dir',
                    "bash",
                    str(ROOT / "scripts" / "runtime-state.sh"),
                    str(runtime_link),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("refusing symlink", result.stderr)

    def test_zellij_launcher_passes_mux_and_pane_map_to_server(self):
        source = (ROOT / "scripts" / "launch-zellij.sh").read_text(encoding="utf-8")
        server_start = source[source.index('Starting MCP server'):source.index('SERVER_PID=$!')]
        self.assertIn('STUDIO_MUX="zellij"', server_start)
        self.assertIn('STUDIO_PANE_MAP_FILE="$PANE_MAP"', server_start)
        self.assertNotIn('/tmp/studio-zellij-panes.json', source)


if __name__ == "__main__":
    unittest.main()

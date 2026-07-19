import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class MuxStateTests(unittest.TestCase):
    def test_zellij_pane_map_survives_an_importing_process_exit(self):
        with tempfile.TemporaryDirectory(prefix="studio-pane-map-") as temp_dir:
            pane_map = Path(temp_dir) / "panes.json"
            pane_map.write_text('{"agent-1": "1"}', encoding="utf-8")
            env = os.environ.copy()
            env.update({
                "PYTHONPATH": str(ROOT),
                "STUDIO_MUX": "zellij",
                "STUDIO_PANE_MAP_FILE": str(pane_map),
            })

            result = subprocess.run(
                [sys.executable, "-c", "import studio.mux"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(pane_map.exists())
            self.assertEqual(pane_map.read_text(encoding="utf-8"), '{"agent-1": "1"}')

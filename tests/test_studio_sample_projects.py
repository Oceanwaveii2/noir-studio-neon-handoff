import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.request import urlopen

from tools.studio_ui import REPO_ROOT, run_server


class TestStudioSampleProjects(unittest.TestCase):
    PORT = 8797

    @classmethod
    def setUpClass(cls):
        cls.fixture_dir = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.fixture_dir.cleanup)
        fixture = Path(cls.fixture_dir.name)
        cls.server_thread = threading.Thread(
            target=run_server,
            kwargs={
                "port": cls.PORT,
                "timeline_path": fixture / "timeline.sqlite",
                "form_store": fixture / "forms.sqlite",
            },
            daemon=True,
        )
        cls.server_thread.start()
        time.sleep(1)

    def test_sample_projects_endpoint_serves_all_six_characters(self):
        with urlopen(f"http://127.0.0.1:{self.PORT}/api/sample-projects", timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            payload = json.loads(resp.read().decode("utf-8"))
        projects = {p["id"]: p for p in payload.get("projects", [])}
        self.assertIn("american_foxy_momma", projects)
        self.assertIn("green_room_unseen", projects)

        afm = projects["american_foxy_momma"]
        chars = {c["id"]: c for c in afm["characters"]}
        self.assertEqual(
            set(chars.keys()),
            {"rainee", "rainee_peter", "three_bitches", "stella", "haley", "francine"},
        )
        stella_ports = {p["key"]: p for p in chars["stella"]["ports"]}
        self.assertEqual(len(stella_ports["steve"]["episodes"]), 36)
        self.assertEqual(len(stella_ports["aha"]["aha_items"]), 8)
        fran_ports = {p["key"]: p for p in chars["francine"]["ports"]}
        self.assertIn("nurse_franny", fran_ports)
        self.assertEqual(fran_ports["nurse_franny"]["voice_archetype"], "breathy_marilyn_purr")
        for c in afm["characters"]:
            if c.get("portrait") and c["portrait"].startswith("/images/"):
                fname = c["portrait"].split("/images/", 1)[1]
                self.assertTrue((REPO_ROOT / "work/americandad/foxy_mo2_images" / fname).exists())


if __name__ == "__main__":
    unittest.main()

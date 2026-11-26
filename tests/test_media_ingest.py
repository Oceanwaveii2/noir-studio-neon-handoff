"""Unit tests for CN-1: tools/media_ingest.py."""

import tempfile
import unittest
from pathlib import Path

from tools.media_ingest import ingest_media_to_baseline_graph


class TestMediaIngest(unittest.TestCase):
    def test_srt_ingest_produces_immutable_g0_packet(self):
        srt_content = (
            "1\n"
            "00:00:01,000 --> 00:00:04,500\n"
            "FRANCINE: I need a break from Langley.\n\n"
            "2\n"
            "00:00:05,250 --> 00:00:09,000\n"
            "[ROGER] Spring break it is, baby.\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            srt_path = Path(tmp) / "spring_break.srt"
            srt_path.write_text(srt_content, encoding="utf-8")

            packet = ingest_media_to_baseline_graph(srt_path)

        self.assertEqual(packet["schema_version"], "7.0")
        self.assertEqual(packet["branch_id"], "G0")
        self.assertIsNone(packet["parent_branch_id"])
        self.assertTrue(packet["immutable"])
        self.assertEqual(len(packet["source_sha256"]), 64)
        self.assertEqual(len(packet["scenes"]), 2)
        self.assertEqual(packet["scenes"][0]["id"], "E01")
        self.assertEqual(packet["scenes"][0]["start_ms"], 1000)
        self.assertEqual(packet["scenes"][0]["speakers"], ["FRANCINE"])
        self.assertEqual(packet["scenes"][1]["id"], "E02")
        self.assertEqual(packet["scenes"][1]["start_ms"], 5250)
        self.assertEqual(packet["scenes"][1]["speakers"], ["ROGER"])
        self.assertEqual(
            packet["causal_edges"],
            [{"from": "E01", "to": "E02", "kind": "ENABLES"}],
        )

    def test_video_paired_with_srt_uses_video_hash_and_srt_scenes(self):
        with tempfile.TemporaryDirectory() as tmp:
            video_path = Path(tmp) / "episode.mp4"
            video_path.write_bytes(b"FAKE_MP4_BYTES")
            srt_path = Path(tmp) / "episode.srt"
            srt_path.write_text(
                "1\n00:00:00,500 --> 00:00:02,000\nSTAN: What is happening?\n",
                encoding="utf-8",
            )

            packet = ingest_media_to_baseline_graph(video_path, srt_path=srt_path)

        self.assertEqual(packet["branch_id"], "G0")
        self.assertEqual(packet["scenes"][0]["speakers"], ["STAN"])
        self.assertIn("What is happening?", packet["scenes"][0]["text"])

    def test_missing_media_raises_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            ingest_media_to_baseline_graph(Path("nonexistent_media_file.mp4"))


if __name__ == "__main__":
    unittest.main()

"""Tests for Milestone M12: De Novo Scene Synthesizer."""

import unittest
from pathlib import Path

from prose_engine.voice.synthesizer import (
    DeNovoSynthesizer,
    DialogueLine,
    DramaticBeat,
    extract_dialogue_skeleton,
    verify_dialogue_invariant,
)


class SynthesizerTests(unittest.TestCase):
    def setUp(self):
        self.sample_script = (
            "INT. LIVING ROOM - MORNING\n\n"
            "Francine stands by the door.\n\n"
            "FRANCINE\\ (rolling her eyes)\\ Time to let it all out.\n\n"
            "Rainee clutches her stomach.\n\n"
            "RAINEE\\ (groaning)\\ My intestines are staging a revolution.\n\n"
            "STELLA\\ Still hot. Objectively.\n"
        )
        self.skeleton = extract_dialogue_skeleton(self.sample_script)

    def test_extract_dialogue_skeleton(self):
        self.assertEqual(len(self.skeleton), 3)
        self.assertEqual(self.skeleton[0].speaker, "FRANCINE")
        self.assertEqual(self.skeleton[0].parenthetical, "rolling her eyes")
        self.assertEqual(self.skeleton[0].text, "Time to let it all out.")
        self.assertEqual(self.skeleton[2].speaker, "STELLA")
        self.assertEqual(self.skeleton[2].text, "Still hot. Objectively.")

    def test_verify_dialogue_invariant_exact(self):
        good_prose = (
            "Francine paused, taking in the morning light. 'Time to let it all out.' "
            "Rainee leaned against the wall with both hands. 'My intestines are staging a revolution.' "
            "Stella took a slow sip. 'Still hot. Objectively.'"
        )
        ok, missing = verify_dialogue_invariant(self.skeleton, good_prose)
        self.assertTrue(ok)
        self.assertEqual(missing, [])

    def test_verify_dialogue_invariant_catches_missing(self):
        bad_prose = (
            "Francine smiled. 'Time to let it all out.' "
            "Stella took a slow sip. 'Still hot. Objectively.'"
        )
        ok, missing = verify_dialogue_invariant(self.skeleton, bad_prose)
        self.assertFalse(ok)
        self.assertEqual(len(missing), 1)
        self.assertIn("RAINEE", missing[0])

    def test_assemble_synthesis_prompt_contains_all_blocks(self):
        synth = DeNovoSynthesizer("tarantino")
        beats = [
            DramaticBeat("b1", "Francine announces departure", props=["overnight bag"]),
            DramaticBeat("b2", "Rainee suffers abdominal pressure", props=["sofa"]),
        ]
        prompt = synth.assemble_synthesis_prompt(
            scene_heading="INT. LIVING ROOM - MORNING",
            beats=beats,
            skeleton=self.skeleton,
            seed=42,
        )
        self.assertIn("DE NOVO SCENE SYNTHESIZER", prompt)
        self.assertIn("QUENTIN TARANTINO", prompt)
        self.assertIn("INVIOLABLE DIALOGUE SKELETON", prompt)
        self.assertIn("Time to let it all out.", prompt)
        self.assertIn("HARD-BANNED SLOP CLICHES", prompt)

    def test_validate_candidate_flags_cliches(self):
        synth = DeNovoSynthesizer("irby")
        cliche_prose = (
            "Francine smiled. 'Time to let it all out.' "
            "Then a baritone trombone glissando shook the linoleum with pneumatic force. "
            "Rainee leaned against the wall. 'My intestines are staging a revolution.' "
            "Stella took a slow sip. 'Still hot. Objectively.'"
        )
        ok, issues = synth.validate_candidate(self.skeleton, cliche_prose)
        self.assertFalse(ok)
        self.assertTrue(any("blacklisted" in issue for issue in issues))


if __name__ == "__main__":
    unittest.main()

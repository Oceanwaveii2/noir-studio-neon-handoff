"""Conservative text-only labels for imported writing blocks."""
import subprocess
import unittest


class ImportedCaptionTests(unittest.TestCase):
    def test_explicit_cues_and_ambiguous_dialogue(self):
        js=r'''
const assert=require('assert');const c=require('./tools/compose_blocks.js');
assert.deepStrictEqual(c.inferLabel('The kitchen fell silent.'),{label:'Narrator',kind:'narrator'});
assert.deepStrictEqual(c.inferLabel('FRANCINE: Did you hear that?'),{label:'FRANCINE',kind:'character'});
assert.deepStrictEqual(c.inferLabel('ROGER\nI heard everything.'),{label:'ROGER',kind:'character'});
assert.deepStrictEqual(c.inferLabel('“Hello,” Francine said, watching the door.'),{label:'Francine',kind:'character'});
assert.deepStrictEqual(c.inferLabel('“Hello,” she said.'),{label:'Dialogue',kind:'character'});
assert.deepStrictEqual(c.inferLabel('"Did you hear that?"'),{label:'Dialogue',kind:'character'});
assert.deepStrictEqual(c.inferLabel('### SCENE 1: KITCHEN'),{label:'Scene',kind:'narrator'});
assert.deepStrictEqual(c.inferLabel('INT. KITCHEN'),{label:'Scene',kind:'narrator'});
'''
        result=subprocess.run(['node','-e',js],capture_output=True,text=True,encoding='utf-8',timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':unittest.main()

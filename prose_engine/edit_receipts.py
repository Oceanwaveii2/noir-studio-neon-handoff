"""Idempotent notebook edits. A receipt describes the original commit only."""
from __future__ import annotations

from dataclasses import dataclass
import json
import re

from story_graph.director import fingerprint


_IDENTIFIER = re.compile(r'[A-Za-z0-9_.:-]{1,125}\Z')


def ensure(c):
    c.execute('''CREATE TABLE IF NOT EXISTS episode_edit_receipts(
                 episode TEXT NOT NULL REFERENCES episodes(id), key TEXT NOT NULL,
                 checksum TEXT NOT NULL, outcome TEXT NOT NULL, PRIMARY KEY(episode,key))''')


@dataclass(frozen=True)
class EditReceipt:
    episode: str
    key: str
    checksum: str
    action: str

    @classmethod
    def make(cls, action, episode, request, key=None):
        checksum = fingerprint([action, episode, request])
        if key is not None and (not isinstance(key,str) or not _IDENTIFIER.fullmatch(key)):
            raise ValueError('Invalid edit request ID')
        return cls(episode, key or checksum, checksum, action)

    def read(self, c):
        row = c.execute('SELECT checksum,outcome FROM episode_edit_receipts WHERE episode=? AND key=?',
                        (self.episode,self.key)).fetchone()
        if row is None:
            return None
        if row['checksum'] != self.checksum:
            raise ValueError('Request ID already belongs to a different edit')
        return json.loads(row['outcome'])

    def check_new(self, c):
        if self.read(c):
            raise ValueError('This edit already has a receipt')

    def record(self, c, notebook_revision, timeline_revision):
        receipt = {'id':self.key,'action':self.action,'episode':self.episode,
                   'notebook_revision':notebook_revision,'timeline_revision':timeline_revision}
        c.execute('INSERT INTO episode_edit_receipts VALUES(?,?,?,?)',
                  (self.episode,self.key,self.checksum,json.dumps(receipt)))
        return receipt

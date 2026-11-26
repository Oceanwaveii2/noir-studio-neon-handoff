"""Opt-in evidence comparison; no automatic promotion to narrative context."""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re


def _distance(left, right):
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j-1] + (a != b)))
        previous = current
    return previous[-1]


def compare_ocr(reference: str, candidate: str) -> dict:
    """Compare against an independently corrected page, retaining actual insertions."""
    words = lambda s: re.findall(r"\b\w+\b", s.casefold())
    rw, cw = words(reference), words(candidate)
    ref_lines = [x.strip() for x in reference.splitlines() if x.strip()]
    out_lines = [x.strip() for x in candidate.splitlines() if x.strip()]
    left, right = Counter(ref_lines), Counter(out_lines)
    shared_order_left = [x for x in ref_lines if x in right]
    shared_order_right = [x for x in out_lines if x in left]
    return {'character_errors': _distance(reference, candidate),
            'character_error_rate': _distance(reference, candidate) / len(reference) if reference else None,
            'word_errors': _distance(rw, cw),
            'word_error_rate': _distance(rw, cw) / len(rw) if rw else None,
            'omitted_lines': list((left-right).elements()),
            'candidate_only_lines': list((right-left).elements()),
            'shared_line_order_matches': shared_order_left == shared_order_right,
            'note': 'Candidate-only lines are possible inventions or OCR errors and need human inspection.'}


def compare_timed(reference: list[dict], candidate: list[dict]) -> dict:
    """Compare aligned events by ID, without inferring speakers or sound from text."""
    def validate(rows):
        result = {}
        for r in rows:
            if not isinstance(r.get('id'), str) or not r['id'] or r['id'] in result:
                raise ValueError('Each event needs a unique ID.')
            if not 0 <= r['start'] < r['end']:
                raise ValueError('Event times must be nonnegative and ordered.')
            result[r['id']] = r
        return result
    a, b = validate(reference), validate(candidate)
    pairs = []
    for key in sorted(a.keys() & b.keys()):
        x, y = a[key], b[key]
        pairs.append({'id': key, 'start_error_seconds': abs(x['start']-y['start']),
                      'end_error_seconds': abs(x['end']-y['end']),
                      'speaker_matches': x.get('speaker') == y.get('speaker'),
                      'label_matches': x.get('label') == y.get('label'),
                      'text_matches': x.get('text') == y.get('text')})
    return {'matched': pairs, 'missing_ids': sorted(a.keys()-b.keys()),
            'extra_ids': sorted(b.keys()-a.keys()), 'note': 'Matches require independently aligned event IDs; overlap is preserved.'}


@dataclass(frozen=True)
class Evidence:
    kind: str
    source_id: str
    locator: str
    extraction_revision: str
    raw: str
    reviewed: str = ''
    reviewer: str = ''
    permission: str = 'unknown'

    def __post_init__(self):
        if self.kind not in ('ocr', 'audio') or not all((self.source_id, self.locator, self.extraction_revision)):
            raise ValueError('Evidence requires kind, source, locator and extraction revision.')
        if self.permission not in ('unknown', 'denied', 'permitted'):
            raise ValueError('Invalid permission state.')

    def context(self):
        if self.permission != 'permitted' or not self.reviewer.strip() or not self.reviewed.strip():
            raise PermissionError('Evidence must be permitted and reviewed before context export.')
        return {'source_id': self.source_id, 'locator': self.locator,
                'extraction_revision': self.extraction_revision, 'reviewer': self.reviewer,
                'text': self.reviewed, 'raw_sha256': hashlib.sha256(self.raw.encode()).hexdigest()}

    def record(self):
        return asdict(self)


def save_evidence(record: Evidence, path: str | Path) -> None:
    """Write one immutable raw/reviewed record, refusing an existing destination."""
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(record.record(), stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def load_evidence(path: str | Path) -> Evidence:
    with Path(path).open(encoding='utf-8') as stream:
        return Evidence(**json.load(stream))

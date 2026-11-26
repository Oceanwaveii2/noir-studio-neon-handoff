"""Evidence-linked, scoped meaning diagnostics; no provider or canon writes.

Rules assess only narrow patterns and explicit structured claims. A lack of
matches is an unavailable assessment, never evidence the prose is correct.
"""
from __future__ import annotations
import hashlib
import re
from story_graph.typed_laws import validate_world_claim
from story_graph.world_laws import parentage_findings

_NEGATIVE_PARENTAGE = re.compile(
    r"\bHaley\s+(?:(?:does\s+not|doesn['’]t)\s+have\s+(?:a\s+)?|has\s+no\s+)(?:biological\s+)?(?:father|dad|daddy)\b(?!-in-law\b|\s+figure\b)"
    r"|\bHaley['’]s\s+(?:biological\s+)?(?:father|dad|daddy)\s+(?:does\s+not|doesn['’]t)\s+exist\b", re.I)
_AMBIGUOUS_PARENTAGE = re.compile(
    r"\b(?:Haley\b.{0,100}\b(?:father|dad|daddy|sire|paternal|biological\s+parent)\b|"
    r"(?:father|dad|daddy|sire|paternal|biological\s+parent)\b.{0,100}\bHaley\b|"
    r"(?:her|his|their)\s+(?:father|dad|daddy)\b)", re.I)
_SEMANTIC_PARENTAGE = re.compile(
    r"\b(?:sire[ds]?|fathered|begot)\s+Haley\b"
    r"|\bHaley\b[^.!?\n]{0,80}\b(?:sired\s+by|fathered\s+by|born\s+to\s+a\s+father|male\s+parent|paternal\s+(?:dna|genes|lineage|parent))\b"
    r"|\b(?:her|a)\s+(?:biological|male|paternal|real)\s+(?:father|dad|daddy|parent)\b[^.!?\n]{0,80}\bHaley\b"
    r"|\bHaley\b[^.!?\n]{0,80}\b(?:biological|male|paternal|real)\s+(?:father|dad|daddy|parent)\b",
    re.I,
)
_COREF_DAD = re.compile(
    r"\bher\s+(?:biological\s+|real\s+)?(?:father|dad|daddy|male\s+parent)\b(?!-in-law\b|\s+figure\b)",
    re.I,
)
_OTHER_FEMALE = re.compile(r"\b(?:Francine|Rainee|Stella|she|wife|Mama)\b", re.I)
_CONTEXT = re.compile(r"[\"“”]|(?:^|\s)'[^']|'\s*$|\b(?:said|says|thought|thinks?|believ\w*|imagined|claimed|alleged|assumed|wondered|joked|joking|pretended|rumou?r|maybe|perhaps|if)\b", re.I)
_NEGATION_CUE = re.compile(r"\b(?:not|never|no|none|neither|without|does\s+not|doesn['’]t)\b", re.I)


def _finding(status,method,reason,*,evidence=None,rule_id=None,rule_source=None,law_revision=None,claim_source=None):
    return {'status':status,'method':method,'confidence':'rule_based' if status in ('supported','contradicted') else 'unresolved',
            'reason':reason,'evidence':evidence,'rule_id':rule_id,'rule_source':rule_source,
            'claim_source':claim_source,'law_revision':law_revision}


def _sentence_bounds(text: str, start: int, end: int) -> str:
    left = max(text.rfind('.', 0, start), text.rfind('!', 0, start), text.rfind('?', 0, start), text.rfind('\n', 0, start)) + 1
    rights = [i for i in (text.find('.', end), text.find('!', end), text.find('?', end), text.find('\n', end)) if i >= 0]
    return text[left:min(rights) if rights else len(text)]


def _in_nonfact_context(text: str, start: int, end: int) -> bool:
    sentence = _sentence_bounds(text, start, end)
    before = sentence[:max(0, start - (text.rfind(sentence) if sentence in text else 0))]
    if _CONTEXT.search(sentence):
        return True
    if before.count('"') % 2 == 1 or ('“' in before and '”' not in before):
        return True
    return False


def _semantic_paraphrase_findings(packet, text: str) -> list[dict]:
    """Detect paraphrased and coreference world-law contradictions without future leakage."""
    findings: list[dict] = []
    laws = getattr(packet, 'world_laws', ()) or ()
    revision = getattr(packet, 'world_law_revision', 0)
    seen_evidence: set[tuple[str, str]] = set()

    for law in laws:
        if not law.get('enabled'):
            continue
        if law.get('matcher') == 'haley_parentage':
            rules = [r for r in law.get('constraints', []) if r['subject'].casefold() == 'haley' and r['predicate'].casefold() == 'father']
            source_id = rules[0]['source_id'] if rules else 'author-context:haley-parentage'
            has_exceptions = any(r['allowed_values'] or r['exceptions'] for r in rules)
            for match in _SEMANTIC_PARENTAGE.finditer(text):
                sent = _sentence_bounds(text, match.start(), match.end())
                if re.search(r'\b(?:does\s+not|doesn[\'’]t|never)\b', sent, re.I) and not _CONTEXT.search(sent):
                    continue
                uncertain = has_exceptions or bool(_CONTEXT.search(sent)) or bool(_NEGATION_CUE.search(sent))
                ev = match.group(0)[:200]
                key = (law['id'], ev.casefold())
                if key in seen_evidence:
                    continue
                seen_evidence.add(key)
                findings.append(_finding(
                    'uncertain' if uncertain else 'contradicted',
                    'semantic_paraphrase',
                    'Paraphrased parentage claim requires author review.' if uncertain else 'Paraphrased biological paternity claim contradicts Haley parentage law.',
                    evidence=ev,
                    rule_id=law['id'],
                    rule_source=source_id,
                    law_revision=revision,
                ))
            # Multi-sentence Haley coreference when a prior sentence mentions Haley and the
            # local sentence refers to "her dad/father" without another clear female referent.
            sentences = [s.strip() for s in re.split(r'(?<=[.!?\n])\s+', text) if s.strip()]
            haley_active = False
            for sent in sentences:
                has_haley = bool(re.search(r'\bHaley\b', sent, re.I))
                if has_haley:
                    haley_active = True
                elif re.search(r'\b(?:Francine|Rainee|Stella|Jeff|Stan)\b', sent):
                    haley_active = False
                if haley_active and not has_haley and (m := _COREF_DAD.search(sent)):
                    if re.search(r'\bBaba\b', sent, re.I) or _OTHER_FEMALE.search(sent[:m.start()]):
                        continue
                    uncertain = has_exceptions or bool(_CONTEXT.search(sent)) or bool(_NEGATION_CUE.search(sent))
                    ev = m.group(0)[:200]
                    key = (law['id'], ev.casefold())
                    if key in seen_evidence:
                        continue
                    seen_evidence.add(key)
                    findings.append(_finding(
                        'uncertain' if uncertain else 'contradicted',
                        'semantic_coreference',
                        'Coreferential parentage mention requires author review.' if uncertain else 'Coreference ("her father/dad" with Haley in scope) contradicts Haley parentage law.',
                        evidence=ev,
                        rule_id=law['id'],
                        rule_source=source_id,
                        law_revision=revision,
                    ))
        elif law.get('matcher') == 'literal':
            for phrase in law.get('phrases', ()):
                tokens = [re.escape(tok) for tok in phrase.strip().split() if tok]
                if len(tokens) < 2:
                    continue
                # Catch flexible whitespace/possessive/plural inflection paraphrases of multi-word banned phrases.
                flex = re.compile(r'\b' + r'\W{1,4}'.join(tokens) + r"(?:s|'s|’s)?\b", re.I)
                for m in flex.finditer(text):
                    if m.group(0).casefold() == phrase.strip().casefold():
                        continue
                    sent = _sentence_bounds(text, m.start(), m.end())
                    uncertain = bool(_CONTEXT.search(sent)) or bool(_NEGATION_CUE.search(sent))
                    ev = m.group(0)[:200]
                    key = (law['id'], ev.casefold())
                    if key in seen_evidence:
                        continue
                    seen_evidence.add(key)
                    findings.append(_finding(
                        'uncertain' if uncertain else 'contradicted',
                        'semantic_paraphrase',
                        'Inflected or punctuated phrase variant conflicts with configured world law.',
                        evidence=ev,
                        rule_id=law['id'],
                        rule_source=law['id'],
                        law_revision=revision,
                    ))
    return findings


def assess_meaning(packet, text, claims=None, *, semantic_review: bool = False):
    """Assess author-supplied claims and narrow prose patterns in packet scope.

    Typed checks judge the supplied claim, not whether its extraction from the
    prose was accurate. No model is invoked; no new fact is committed.
    """
    if not isinstance(text,str):raise ValueError('Text must be text')
    if claims is None:claims=[]
    if not isinstance(claims,list):raise ValueError('Claims must be a list')
    findings=[]
    for claim in claims:
        if not isinstance(claim,dict) or claim.get('kind')!='world_fact':
            raise ValueError('Meaning checks accept explicit structured world facts only')
        for item in validate_world_claim(claim,packet.world_laws,packet.world_law_revision):
            status={'conflict':'contradicted','supported':'supported','uncertain':'uncertain'}[item['status']]
            if item['status']=='uncertain' and item.get('reason','').startswith('No applicable structured rule'):
                status='unavailable'
            findings.append(_finding(status,'structured_claim',item.get('reason','Matches an applicable structured world rule.'),
                evidence={k:claim[k] for k in ('subject','predicate','value','assertion')},
                rule_id=item.get('rule_id'),rule_source=item.get('rule_source'),
                law_revision=item.get('law_revision'),claim_source=item.get('claim_source')))
    parentage=[law for law in packet.world_laws if law.get('matcher')=='haley_parentage' and law.get('enabled')]
    for law in parentage:
        found=parentage_findings(text,law,packet.world_law_revision)
        for item in found:
            status='contradicted' if item['status']=='conflict' else 'uncertain'
            findings.append(_finding(status,'narrow_prose_pattern',item['reason'],evidence=item['evidence'],
                rule_id=item['rule_id'],rule_source=item['rule_source'],law_revision=item['law_revision']))
        for match in _NEGATIVE_PARENTAGE.finditer(text):
            left=max(text.rfind('.',0,match.start()),text.rfind('!',0,match.start()),text.rfind('?',0,match.start()),text.rfind('\n',0,match.start()))+1
            right_candidates=[i for i in (text.find('.',match.end()),text.find('!',match.end()),text.find('?',match.end()),text.find('\n',match.end())) if i>=0]
            sentence=text[left:min(right_candidates) if right_candidates else len(text)]
            rules=[r for r in law.get('constraints',[]) if r['subject'].casefold()=='haley' and r['predicate'].casefold()=='father']
            if not rules:continue
            uncertain=bool(_CONTEXT.search(sentence)) or any(r['allowed_values'] or r['exceptions'] for r in rules)
            findings.append(_finding('uncertain' if uncertain else 'supported','narrow_prose_pattern',
                'A quotation, belief or exception needs author interpretation.' if uncertain else 'The explicit negation matches the active author rule.',
                evidence=match.group(),rule_id=law['id'],rule_source=rules[0]['source_id'],law_revision=packet.world_law_revision))
        if semantic_review:
            sem = _semantic_paraphrase_findings(packet, text)
            findings.extend(sem)
            found = list(found) + sem
        if not found and not _NEGATIVE_PARENTAGE.search(text):
            match=_AMBIGUOUS_PARENTAGE.search(text)
            if match:
                sources=[r['source_id'] for r in law.get('constraints',[]) if r['subject'].casefold()=='haley' and r['predicate'].casefold()=='father']
                findings.append(_finding('uncertain','ambiguous_parentage_cue',
                    'The relationship, subject or speaker is unclear; this is not a contradiction finding.',
                    evidence=match.group()[:200],rule_id=law['id'],rule_source=sources[0] if sources else None,law_revision=packet.world_law_revision))
    if semantic_review:
        for item in _semantic_paraphrase_findings(packet, text):
            if not any(f.get('rule_id') == item.get('rule_id') and f.get('evidence') == item.get('evidence') for f in findings):
                findings.append(item)
    if not findings:
        findings.append(_finding('unavailable','no_applicable_check',
            'No applicable check established the meaning; the prose is not verified.',law_revision=packet.world_law_revision))
    order={'contradicted':3,'uncertain':2,'unavailable':1,'supported':0}
    overall=max((x['status'] for x in findings),key=order.__getitem__)
    return {'schema_version':1,'status':overall,'findings':findings,
        'scope':packet.context.public() if packet.context else None,
        'text_sha256':hashlib.sha256(text.encode('utf-8')).hexdigest(),
        'assessment_scope':'Listed findings only; the overall text is not verified.',
        'coverage':{
            'free_text':'semantic_paraphrase_rules_v1' if semantic_review else 'narrow_patterns_only',
            'structured_claims':len(claims),
            'semantic_verifier':'local_semantic_paraphrase_v1' if semantic_review else 'not_configured',
        },
        'confidence_note':'Rule-based labels are not calibrated probabilities; unmatched prose is not verified.',
        'canonical_write':False}


def assess_semantic_review(packet, text: str, claims=None) -> dict:
    """Run explicit scoped semantic/paraphrase contradiction review without future leakage."""
    return assess_meaning(packet, text, claims, semantic_review=True)

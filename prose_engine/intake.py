"""Preview an author document and save one recoverable, protected episode."""
from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from story_graph.beat_map import map_episode
from story_graph.director import fingerprint
from story_graph.universe_scope import verify_scope
from .cook import classify_saved_blocks
from .notebook import NotebookStore, _blocks, _valid_blocks, digest, joined
from .timeline_commands import revision


MAX_UPLOAD = 32 * 1024 * 1024
MAX_REQUEST = 4 * ((MAX_UPLOAD + 2) // 3) + 1_405_000  # base64 file, optional cover, metadata
MAX_TEXT = 220_000
MAX_SOURCE_CHUNK = 262_144
FORMATS = ('.md','.txt','.fountain','.pdf','.docx')
_W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
_KEY = re.compile(r'[A-Za-z0-9_.:-]{1,125}\Z')
_SHA = re.compile(r'[0-9a-f]{64}\Z')


def _name(value):
    if (not isinstance(value,str) or not 1 <= len(value) <= 220 or
            not value.isprintable() or '/' in value or '\\' in value or ':' in value):
        raise ValueError('Choose a file with a valid name.')
    return value


def _decode(value):
    if not isinstance(value,str) or len(value) > 4*((MAX_UPLOAD+2)//3):
        raise ValueError('Choose a source file up to 32 MB.')
    try:
        raw = base64.b64decode(value,validate=True)
    except (ValueError,binascii.Error) as exc:
        raise ValueError('The selected file could not be read.') from exc
    if not 0 < len(raw) <= MAX_UPLOAD:
        raise ValueError('Choose a nonempty source file up to 32 MB.')
    return raw


def _pdf(raw):
    if b'%PDF-' not in raw[:1024]:
        raise ValueError('This file is not a readable PDF.')
    try:
        import pymupdf
    except ImportError as exc:
        raise ValueError('PDF reading is unavailable in this installation.') from exc
    try:
        with pymupdf.open(stream=raw,filetype='pdf') as doc:
            if doc.needs_pass:
                raise ValueError('Unlock this PDF before importing it.')
            if not 1 <= doc.page_count <= 250:
                raise ValueError('Choose a PDF of up to 250 pages.')
            texts=[]
            empty=[]
            length=0
            for i,page in enumerate(doc,1):
                text=page.get_text('text',sort=True)
                if not text.strip():
                    empty.append(i)
                length += len(text)
                if length > MAX_TEXT:
                    raise ValueError('Extracted text is too long. Split the source into episodes first.')
                texts.append(text)
            return '\n\n'.join(texts),len(texts),empty
    except RuntimeError as exc:
        raise ValueError('The PDF could not be read. Try exporting it again.') from exc


def _docx(raw):
    try:
        with ZipFile(BytesIO(raw)) as z:
            paths=z.namelist()
            if (paths.count('word/document.xml') != 1 or paths.count('[Content_Types].xml') != 1
                    or len(paths) > 3000):
                raise ValueError('Choose a standard Word DOCX file.')
            info=z.getinfo('word/document.xml')
            if info.file_size > 4*1024*1024 or info.flag_bits & 1:
                raise ValueError('The Word document body is too large or locked.')
            xml=z.read(info)
        codec='utf-16' if xml.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8-sig'
        markup=xml.decode(codec)
        if '\0' in markup or re.search(r'<!\s*(?:doctype|entity)\b',markup,re.IGNORECASE):
            raise ValueError('This Word document uses unsupported XML declarations.')
        root=ElementTree.fromstring(markup)
    except (BadZipFile,ElementTree.ParseError,UnicodeError,OSError,RuntimeError,NotImplementedError) as exc:
        raise ValueError('The Word document could not be read. Export a new .docx copy.') from exc
    body=root.find(_W+'body')
    if body is None:
        raise ValueError('No editable Word document body was found.')
    ambiguous={_W+tag for tag in ('ins','del','moveFrom','moveTo','altChunk')}
    if any(node.tag in ambiguous for node in body.iter()):
        raise ValueError('This DOCX has tracked or linked text. Save a resolved copy or export it as text first.')
    blocks=[]
    for paragraph in body.iter(_W+'p'):
        parts=[]
        for x in paragraph.iter():
            if x.tag == _W+'t':
                parts.append(x.text or '')
            elif x.tag == _W+'tab':
                parts.append('\t')
            elif x.tag in (_W+'br',_W+'cr'):
                parts.append('\n')
        blocks.append(''.join(parts))
    return '\n'.join(blocks),None,[]


@dataclass(frozen=True)
class Document:
    name: str
    raw: bytes
    text: str
    pages: int | None
    pages_requiring_ocr: list[int]

    def summary(self):
        return {'name':self.name,'sha256':hashlib.sha256(self.raw).hexdigest(),'text_sha256':digest(self.text),
                'characters':len(self.text),'pages':self.pages,'pages_requiring_ocr':self.pages_requiring_ocr,
                'format':self.name.rsplit('.',1)[-1].upper()}


def _upload(payload):
    if not isinstance(payload,dict):
        raise ValueError('Choose a source file first.')
    name=_name(payload.get('name'))
    if Path(name).suffix.casefold() not in FORMATS:
        raise ValueError('Use Markdown, plain text, Fountain, PDF or Word DOCX.')
    return name,_decode(payload.get('base64'))


def _extract(name, raw):
    suffix=Path(name).suffix.casefold()
    if suffix=='.pdf':
        text,pages,empty=_pdf(raw)
    elif suffix=='.docx':
        text,pages,empty=_docx(raw)
    else:
        try:
            text,pages,empty=raw.decode('utf-8-sig'),None,[]
        except UnicodeDecodeError as exc:
            raise ValueError('Save this source as UTF-8 text before importing.') from exc
    if not text.strip():
        raise ValueError('No selectable text was found. Run OCR on a scanned PDF, or export the text again.')
    if len(text) > MAX_TEXT or '\0' in text or any(0xD800 <= ord(x) <= 0xDFFF for x in text):
        raise ValueError('Extracted content is too long or is not valid text.')
    return Document(name,raw,text,pages,empty)


def read_document(payload):
    return _extract(*_upload(payload))


def preview(request):
    doc=read_document(request.get('document'))
    return {'status':'READY','source':doc.summary(),'text_preview':doc.text[:6400],
            'preview_truncated':len(doc.text)>6400}


def saved_brief(c, episode):
    row=_saved(c,episode)
    return json.loads(row['receipt']) if row else None


def _saved(c, episode):
    if not c.execute("SELECT 1 FROM sqlite_master WHERE name='episode_intake' AND type='table'").fetchone():
        return None
    return c.execute('''SELECT i.rowid AS source_row, i.input_sha256, i.receipt, length(i.original) AS bytes,
                            e.branch, e.head, e.status
                        FROM episode_intake AS i JOIN episodes AS e ON i.episode=e.id WHERE i.episode=?''',
                     (episode,)).fetchone()


def _scope(c, request):
    return verify_scope(c,project_id=request.get('project'),universe_id=request.get('universe'))


def _creation_id(request):
    key=request.get('request_id')
    if not isinstance(key,str) or not _KEY.fullmatch(key):
        raise ValueError('A valid creation ID is required.')
    return key


def _episode_id(scope, key):
    # Keep the original ID formula so preexisting intake records are recoverable.
    return 'ep-'+fingerprint([scope['project_id'],key])[:24]


def receipt(timeline, request):
    key=_creation_id(request)
    with timeline._connect() as c:
        c.execute('BEGIN')
        episode=_episode_id(_scope(c,request),key)
        row=_saved(c,episode)
        if row is None:
            return {'status':'NOT_FOUND','request_id':key}
        return {'status':'COMMITTED','request_id':key,'receipt':json.loads(row['receipt']),
                'current':{'episode':episode,'branch':row['branch'],'status':row['status'],
                           'timeline_revision':row['head']}}


def source(timeline, request):
    episode,branch=request.get('episode'),request.get('branch')
    timeline._required(episode,'episode')
    timeline._required(branch,'branch')
    part=request.get('part','original')
    offset=request.get('offset',0)
    count=request.get('count',MAX_SOURCE_CHUNK)
    if part not in ('original','transcript') or type(offset) is not int or offset<0 or \
            type(count) is not int or not 1<=count<=MAX_SOURCE_CHUNK:
        raise ValueError('Choose an original or transcript byte range up to 256 KiB.')
    with timeline._connect() as c:
        c.execute('BEGIN')
        _scope(c,request)
        row=_saved(c,episode)
        if not row or row['branch']!=branch or row['bytes'] is None:
            raise ValueError('No imported source is saved in this episode and branch.')
        saved=json.loads(row['receipt'])
        meta=saved['source']
        if part=='original':
            total=row['bytes']
            content_hash=meta['sha256']
            if offset>total:
                raise ValueError('Source byte range starts after the end of the file.')
            with c.blobopen('episode_intake','original',row['source_row'],readonly=True) as stream:
                stream.seek(offset)
                data=stream.read(count)
        else:
            initial=c.execute('SELECT script,script_sha256 FROM revisions WHERE episode=? AND revision=?',
                              (episode,saved['timeline_revision'])).fetchone()
            if not initial or initial['script_sha256']!=meta['text_sha256'] or digest(initial['script'])!=meta['text_sha256']:
                raise ValueError('The saved intake transcript could not be verified.')
            exact=initial['script'].encode('utf-8')
            total=len(exact)
            content_hash=meta['text_sha256']
            if offset>total:
                raise ValueError('Source byte range starts after the end of the file.')
            data=exact[offset:offset+count]
        return {'episode':episode,'branch':branch,'part':part,'source':meta,
                'offset':offset,'next_offset':offset+len(data),'total_bytes':total,'sha256':content_hash,
                'timeline_revision':saved['timeline_revision'],'base64':base64.b64encode(data).decode('ascii')}


def create(timeline, request, *, from_document, junctions=()):
    from .providers.session_registry import session_names
    request_id=_creation_id(request)
    title=request.get('title')
    if not isinstance(title,str) or not 1 <= len(title.strip()) <= 200 or not title.strip().isprintable():
        raise ValueError('An episode title is required.')
    title=title.strip()
    prompt=request.get('prompt','')
    writer=request.get('provider','codex-session')
    branch=request.get('branch','main')
    after=request.get('after','end')
    if (not isinstance(prompt,str) or len(prompt)>500 or '\0' in prompt or
            not isinstance(writer,str) or not isinstance(branch,str) or not branch or
            not isinstance(after,str) or not after):
        raise ValueError('Choose a valid branch, placement and writing brief up to 500 characters.')
    name,raw=_upload(request.get('document')) if from_document else ('',None)
    text_hash=request.get('text_sha256')
    file_hash=hashlib.sha256(raw).hexdigest() if raw is not None else None
    if from_document and (request.get('file_sha256')!=file_hash or not isinstance(text_hash,str) or not _SHA.fullmatch(text_hash)):
        raise ValueError('The source differs from the preview. Read the document again before importing.')
    if not from_document and request.get('document') is not None:
        raise ValueError('Use document intake when importing a file.')
    cover=request.get('cover')
    if cover is not None:
        timeline._validate_cover(cover)
    def intent(meta):
        return fingerprint([title,branch,after,cover,prompt,writer,meta])

    def replay(row):
        saved=json.loads(row['receipt'])
        meta=saved['source']
        if (bool(meta)!=from_document or intent(meta)!=row['input_sha256'] or
                (meta and (meta['name'],meta['sha256'],meta['text_sha256'])!=(name,file_hash,text_hash))):
            raise ValueError('This creation ID already belongs to a different episode request.')
        return {**saved,'status':'REPLAYED'}

    with timeline._connect() as c:
        c.execute('BEGIN')
        identity=_episode_id(_scope(c,request),request_id)
        existing=_saved(c,identity)
        if existing is not None:
            # A successfully committed operation does not depend on the parser,
            # current notebook, order, or provider configuration of the retry.
            return replay(existing)
    if writer not in session_names():
        raise ValueError('The selected writing session is unavailable.')
    doc=_extract(name,raw) if from_document else None
    if doc and text_hash!=digest(doc.text):
        raise ValueError('The source differs from the preview. Read the document again before importing.')
    if doc and doc.pages_requiring_ocr and request.get('accept_partial') is not True:
        raise ValueError('Some PDF pages have no selectable text. Run OCR first or choose to import the available text.')
    meta=doc.summary() if doc else None
    script=doc.text if doc else ''
    input_hash=intent(meta)
    blocks=classify_saved_blocks(_blocks(script,name,0),junctions)
    _valid_blocks(blocks)
    if script!=joined(blocks):
        raise ValueError('Could not prepare the imported text exactly.')
    NotebookStore(timeline)  # Existing schema; all new content is written together below.
    with timeline._connect() as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute('''CREATE TABLE IF NOT EXISTS episode_intake (
            episode TEXT PRIMARY KEY REFERENCES episodes(id), input_sha256 TEXT NOT NULL,
            receipt TEXT NOT NULL, original BLOB)''')
        _scope(c,request)
        existing=_saved(c,identity)
        if existing is not None:
            return replay(existing)
        if 'expected_revision' in request:
            if revision(request,'expected_revision') != timeline._action_history_stacks(c)[0]:
                raise ValueError('Timeline changed elsewhere. Refresh and try again.')
        if not c.execute('SELECT 1 FROM branches WHERE id=?',(branch,)).fetchone():
            raise ValueError('That timeline branch no longer exists.')
        position=c.execute('SELECT COALESCE(MAX(position),-10)+10 FROM episodes WHERE branch=?',(branch,)).fetchone()[0]
        timeline._create_episode_locked(c,identity,title,branch,position,cover,after=None if after=='end' else after,
                                        script=script,source_name=name)
        state={'schema_version':1,'episode':identity,'branch':branch,'default_protection':100,'blocks':blocks,'masks':[]}
        c.execute('INSERT INTO notebook_heads VALUES(?,0)',(identity,))
        c.execute('INSERT INTO notebook_revisions VALUES(?,?,?,?)',(identity,0,0,json.dumps(state,ensure_ascii=False)))
        mapping=map_episode(timeline,identity,0,_connection=c)
        result={'status':'CREATED','request_id':request_id,'episode':identity,'title':title,'branch':branch,'source':meta,
                'prompt':prompt,'provider':writer,'timeline_revision':0,'notebook_revision':0,
                'scenes':len(mapping['scenes']),'passages':len(mapping['beats']),
                'linked_speakers':len({b['speaker'] for b in blocks if b.get('speaker')}),
                'unresolved':sum(b['kind']=='unresolved' for b in blocks)}
        c.execute('INSERT INTO episode_intake VALUES(?,?,?,?)',(identity,input_hash,json.dumps(result,ensure_ascii=False),doc.raw if doc else None))
        return result

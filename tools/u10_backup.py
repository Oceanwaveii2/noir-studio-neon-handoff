"""Back up an episode timeline with SQLite's consistent online backup API."""
from __future__ import annotations
import argparse
from contextlib import ExitStack, closing
from pathlib import Path
import hashlib
import json
import re
import shutil
import sqlite3
import stat
from tools.u8_recovery import copy_database


DATABASES = ('timeline.sqlite', 'character-forms.sqlite')
MEDIA = ('timeline.clips', 'timeline.media')
MANIFEST = 'noir-workspace.json'


def _regular(path, *, directory=False):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0):
        raise ValueError('Choose workspace files and directories that are not links')
    if not (path.is_dir() if directory else path.is_file()):
        raise ValueError('A required workspace file or directory is missing')
    return path.resolve(strict=True)


def _digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def _check_database(db):
    if db.execute('PRAGMA integrity_check').fetchone() != ('ok',):
        raise ValueError('Backup integrity check failed')
    if db.execute('PRAGMA foreign_key_check').fetchone() is not None:
        raise ValueError('Backup has invalid references')


def backup(source: Path, destination: Path) -> dict:
    source = _regular(source)
    copy_database(source, destination)
    with closing(sqlite3.connect(destination.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        _check_database(db)
        counts = {table: db.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in ('branches','episodes','revisions','events')}
    return {'status':'PASS','file':str(destination.resolve()),'sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),'counts':counts}


def _media(root):
    entries = {}
    for name in MEDIA:
        folder = root/name
        if not folder.exists() and not folder.is_symlink():
            continue
        for path in sorted(_regular(folder, directory=True).iterdir()):
            if not re.fullmatch('[a-f0-9]{64}', path.stem) or not path.suffix:
                raise ValueError('Wait for media intake to finish before taking a checkpoint')
            if _digest(_regular(path)) != path.stem:
                raise ValueError('A saved media original does not match its fingerprint')
            entries[f'{name}/{path.name}'] = path.stem
    return entries


def _bundle_files(root):
    return {name: _digest(_regular(root/name)) for name in DATABASES} | _media(root)


def workspace_snapshot(source: Path, destination: Path) -> dict:
    """Save one stable timeline, forms store and portable media set."""
    source = _regular(source, directory=True)
    destination = destination.resolve()
    if destination == source or source in destination.parents:
        raise ValueError('Choose a new checkpoint folder outside the source workspace')
    media = _media(source)
    with ExitStack() as stack:
        readers = [stack.enter_context(closing(sqlite3.connect(_regular(source/name).as_uri()+'?mode=ro',uri=True)))
                   for name in DATABASES]
        versions = [db.execute('PRAGMA data_version').fetchone() for db in readers]
        destination.mkdir()
        for name, reader in zip(DATABASES, readers):
            with closing(sqlite3.connect(destination/name)) as saved:
                reader.backup(saved)
                _check_database(saved)
        for name in media:
            target = destination/name
            target.parent.mkdir(exist_ok=True)
            shutil.copy2(_regular(source/name),target)
        files = _bundle_files(destination)
        if (_media(source) != media or any(files[name] != sha for name,sha in media.items()) or
                [db.execute('PRAGMA data_version').fetchone() for db in readers] != versions):
            raise ValueError('The workspace changed during checkpoint. Retry from a stable copy.')
    manifest = {'schema_version':1,'files':files}
    with (destination/MANIFEST).open('x',encoding='utf-8') as output:
        json.dump(manifest,output,indent=2)
        output.write('\n')
    return manifest


def workspace_restore(source: Path, destination: Path) -> dict:
    source = _regular(source,directory=True)
    destination = destination.resolve()
    if source in destination.parents:
        raise ValueError('Choose a new restore folder outside the checkpoint')
    manifest = json.loads(_regular(source/MANIFEST).read_text('utf-8'))
    if manifest != {'schema_version':1,'files':_bundle_files(source)}:
        raise ValueError('The workspace checkpoint does not match its manifest')
    for name in DATABASES:
        with closing(sqlite3.connect((source/name).as_uri()+'?mode=ro',uri=True)) as saved:
            _check_database(saved)
    destination.mkdir()
    for name in manifest['files']:
        target = destination/name
        target.parent.mkdir(exist_ok=True)
        shutil.copy2(_regular(source/name),target)
    if _bundle_files(destination) != manifest['files']:
        raise ValueError('The restored workspace does not match the checkpoint')
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True,help='New backup file; never overwritten')
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--workspace',action='store_true',help='Back up a workspace directory and its media')
    mode.add_argument('--restore-workspace',action='store_true',help='Restore a verified workspace checkpoint')
    args=parser.parse_args()
    operation = workspace_snapshot if args.workspace else workspace_restore if args.restore_workspace else backup
    try: print(json.dumps(operation(args.source,args.out),indent=2))
    except (OSError,ValueError,sqlite3.Error) as exc: parser.exit(2,f'Timeline backup unavailable: {exc}\n')

if __name__ == '__main__': main()

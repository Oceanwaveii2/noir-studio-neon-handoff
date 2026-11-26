import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from prose_engine import paths as prose_paths

search_terms = ['neural physics', 'neural_physics', 'physics', 'guard_copies', 'copy_issues', 'staging_violations', 'anti_borrowing', 'borrowing']

root_dir = str(prose_paths.root())
for root, dirs, files in os.walk(root_dir):
    if any(skip in root for skip in ['.git', '__pycache__', 'node_modules', '.venv', 'dist']):
        continue
    for f in files:
        if f.endswith(('.py', '.json', '.md', '.txt')):
            p = os.path.join(root, f)
            try:
                with open(p, 'r', encoding='utf-8', errors='ignore') as fp:
                    content = fp.read().lower()
                    for term in search_terms:
                        if term in content:
                            print(f'Found "{term}" in: {p}')
            except Exception:
                pass

"""Read-only inventory of existing reference indexes; no text or model download."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import sys
from pathlib import Path

import joblib
import numpy as np


def digest(path):
    h=hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024*1024), b""):
            h.update(block)
    return h.hexdigest()


def inspect(path):
    before=digest(path)
    data=joblib.load(path)
    vectors=np.asarray(data["vectors"])
    texts,meta=data["texts"],data["meta"]
    if (vectors.ndim != 2 or len(texts) != len(meta) or len(texts) != vectors.shape[0]
            or not np.isfinite(vectors).all()):
        raise ValueError(f"{path.name}: invalid index rows or vectors")
    sources={}
    chunks=[]
    for pos,(text,row) in enumerate(zip(texts,meta)):
        if not isinstance(text,str) or not isinstance(row,dict):
            raise ValueError(f"{path.name}: malformed passage metadata")
        source=row.get("source_id") or row.get("book")
        if not isinstance(source,str) or not source:
            raise ValueError(f"{path.name}: source identifier missing")
        sources[source]=sources.get(source,0)+1
        chunks.append({"position":pos,"source_id":source,
                       "text_sha256":hashlib.sha256(text.encode("utf-8")).hexdigest(),
                       "passage_id":row.get("passage_id"),"source_revision":row.get("source_revision")})
    after=digest(path)
    if before != after:
        raise ValueError(f"{path.name}: file changed during inspection")
    return {"file":str(path.resolve()),"sha256":before,"rows":len(texts),"dimensions":vectors.shape[1],
            "dtype":str(vectors.dtype),"finite":True,"sources":sources,"chunks":chunks,
            "backend":data.get("backend","unknown-legacy"),"model":data.get("model_name","unknown-legacy"),
            "manifest":data.get("manifest"),"legacy_unverified":not bool(data.get("manifest"))}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--books",required=True)
    parser.add_argument("--out",required=True,help="New manifest file; never overwritten")
    args=parser.parse_args(argv)
    try:
        output=Path(args.out)
        if output.exists():
            raise FileExistsError("Inventory destination already exists")
        root=Path(args.books)
        packages={}
        for name in ("torch","transformers","sentence-transformers","numpy"):
            try: packages[name]=importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError: packages[name]="unavailable"
        results={}
        for name in ("vector_index.joblib","luar_index.joblib","style_index.joblib"):
            path=root/name
            results[name]=inspect(path) if path.is_file() else {"status":"missing"}
        style=root/"styleprint.json"
        payload={"schema_version":1,"kind":"read-only-reference-index-inventory",
                 "packages":packages,"style_model_sha256":digest(style) if style.is_file() else None,
                 "indexes":results,
                 "warning":"Legacy index build revision and preprocessing cannot be inferred from file presence."}
        output.parent.mkdir(parents=True,exist_ok=True)
        with output.open("x",encoding="utf-8",newline="\n") as out:
            json.dump(payload,out,ensure_ascii=False,separators=(",",":"))
            out.write("\n")
        print("Reference index inventory saved:",output)
        return 0
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print(f"Reference index audit unavailable: {exc}",file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

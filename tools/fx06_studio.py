"""Prepare the isolated, source-bound FX06 Studio workspace."""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

from prose_engine.notebook import NotebookStore, digest
from story_graph import fx06_scene as scene
from story_graph.episode_timeline import TimelineStore
from story_graph.form_graph_store import FormGraphStore
from story_graph.source_imports import junctions
from story_graph.world_laws import WorldLawStore


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "deliverables" / "NOIR_FX06_GAG_COLLECTION_20261116"


def scene_graph():
    nodes = [{"id": event, "label": event.replace("-", " ").title()} for event in scene.EVENTS]
    nodes += [{"id": form, "label": speaker, "kind": "cast"}
              for form,speaker in zip(scene.CAST,scene.SPEAKERS)]
    edges = [{"from": a, "to": b} for a,b in zip(scene.EVENTS,scene.EVENTS[1:]) if a != "split"]
    for form in scene.CAST:
        edges.extend([{"from":"split","to":form},{"from":form,"to":"roast"}])
    return {"nodes":nodes, "edges":edges}


def prepare(workspace: Path, bundle_root: Path = BUNDLE) -> dict:
    bundle_root = Path(bundle_root).resolve(strict=True)
    compiled = scene.load_bundle(bundle_root)
    workspace = Path(workspace).resolve()
    if not workspace.parent.is_dir():
        raise ValueError("Choose a new workspace inside an existing local directory")
    workspace.mkdir(exist_ok=False)
    store = TimelineStore(workspace / "timeline.sqlite", project_id=scene.PROJECT, universe_id=scene.UNIVERSE)
    store.add_starter_cards()  # the AFM universe and its existing world-law fixtures, in this copy only
    WorldLawStore(store)
    store.fork(scene.BRANCH,"main","spring-break",0)
    store.create_episode(scene.EPISODE,"FX06 · Rainee split scene",scene.BRANCH,10)
    script = "".join(text for _,_,text in scene.source_sections())
    store.save(scene.EPISODE,0,graph=scene_graph(),script=script,
               source_name="FX06 authored split test (D09 and D17 source)")
    forms_path=workspace/"character-forms.sqlite"
    with store._connect() as c:
        imported = scene.with_cast(junctions(c,{}),compiled)
    forms = FormGraphStore(forms_path, imported=imported)
    links = {}
    for actor in compiled["actors"]:
        fid=actor["form_id"]
        port=f"character:rainee:form:{fid}"
        forms.change({"action":"create_mind_link","kind":"digital_mind","port":port,
                      "label":actor["mind_label"],"revision":forms.read()["revision"]})
        current = next(f for f in forms.junctions()["rainee"].forms if f.id==fid)
        links[fid]=current.link.node_id
        content = {
            "text_fields":{
                "notes":"Bound FX06 evidence for this Rainee manifestation. Available to the writer only during the authored split.",
                "behavior":"\n".join(f'When {t["when"]}: {t["try"]}' for t in actor["tendencies"]),
            },
            "fx06_evidence": [compiled["evidence"][i] for i in
                              sorted({e for t in actor["tendencies"] for e in t["evidence"]})],
        }
        forms.change({"action":"save_node_data","character":"rainee","node":"data:"+port,
                      "content":content, "revision":forms.read()["revision"]})
    binding = scene.register(store,{**compiled,"mind_nodes":links},script)
    roast = next(p for p in binding["phases"] if p["id"]=="roast")
    locked = script.index(scene.PERFUME_LINE)
    masks = [
        {"id":"fx06-exact-D09","start":locked,"end":locked+len(scene.PERFUME_LINE),
         "value":100,"hard":True,"sha256":digest(scene.PERFUME_LINE)},
        {"id":"fx06-roast-editable","start":roast["start"],"end":roast["end"],
         "value":25,"sha256":digest(script[roast["start"]:roast["end"]])},
    ]
    notebooks=NotebookStore(store)
    before=notebooks.open(scene.EPISODE)
    notebook=notebooks.save(scene.EPISODE,before["revision"],before["timeline_revision"],before["blocks"],100,masks)
    context={"project":scene.PROJECT,"universe":scene.UNIVERSE,"episode":scene.EPISODE,
             "branch":scene.BRANCH,"revision":notebook["timeline_revision"]}
    receipt={"timeline":str(workspace/"timeline.sqlite"),"forms":str(forms_path),"scope":context,
             "notebook_revision":notebook["revision"],"roast":roast,"mind_nodes":links,
             "source_sha256":binding["source_sha256"],"package":str(bundle_root)}
    (workspace/"prepared.json").write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8")
    return receipt


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace",type=Path,help="new private Studio workspace directory")
    parser.add_argument("--bundle",type=Path,default=BUNDLE)
    args=parser.parse_args(argv)
    print(json.dumps(prepare(args.workspace,args.bundle),indent=2))


if __name__=="__main__":
    main()

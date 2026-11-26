"""
Aesthetic & Element Feature Ledger Extractor.
Milestone M-PE1: Aesthetic & Element Feature Ledger Extractor.
Analyzes BeatPackets to extract anatomical, somatic, domestic, and comedic features,
generating targeted vector query paths and routing policies for System B.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .lexicon import LEXICON_REGISTRY
from .models import AestheticFeature, BeatAestheticProfile, FeatureCategory


class AestheticFeatureLedger:
    """
    Semantic pre-pass processor for the Prose Engine.
    Converts raw beat packets into an Aesthetic Feature Ledger with targeted vector queries.
    """

    def __init__(self, custom_lexicon: Optional[List[Dict[str, Any]]] = None):
        self.lexicon = custom_lexicon or LEXICON_REGISTRY

    def extract_from_packet(self, packet_data: Dict[str, Any]) -> BeatAestheticProfile:
        beat_id = packet_data.get("beat_id", "unknown_beat")
        scene_id = packet_data.get("scene_id", "unknown_scene")
        desc = packet_data.get("description", "")
        raw_tags = packet_data.get("aesthetic_tags", [])
        clean_tags = " ".join([t.replace("_", " ") for t in raw_tags] + raw_tags)
        
        # Dialogue text concatenation
        dialogue_lines = []
        for d in packet_data.get("raw_dialogue", []):
            if isinstance(d, dict):
                dialogue_lines.append(d.get("text", ""))
                dialogue_lines.append(d.get("parenthetical", ""))
        dialogue_corpus = " ".join([l for l in dialogue_lines if l])

        # Somatic and physique context
        somatic_terms = []
        somatic_ctx = packet_data.get("somatic_context", {})
        for char_data in somatic_ctx.values():
            somatic_dict = char_data.get("somatic", {})
            for k, v in somatic_dict.items():
                somatic_terms.append(f"{k} {v}")
            physique_dict = char_data.get("physique", {})
            for k, v in physique_dict.items():
                somatic_terms.append(f"{k} {v}")
        somatic_corpus = " ".join(somatic_terms).replace("_", " ")

        full_search_text = f"{desc} {clean_tags} {dialogue_corpus} {somatic_corpus}"

        matched_features: List[AestheticFeature] = []
        routing_votes: Dict[str, int] = {}
        vector_queries: List[str] = []
        mandatory_anchors: List[str] = []

        for entry in self.lexicon:
            matched_terms: Set[str] = set()
            for pattern in entry["patterns"]:
                matches = re.findall(pattern, full_search_text, re.IGNORECASE)
                for m in matches:
                    if isinstance(m, tuple):
                        matched_terms.add(m[0] if m[0] else m[1])
                    else:
                        matched_terms.add(m)

            if matched_terms:
                feature = AestheticFeature(
                    id=entry["id"],
                    category=entry["category"],
                    label=entry["label"],
                    matched_terms=sorted(list(matched_terms)),
                    sensory_anchors=entry.get("sensory_anchors", []),
                    routing_hint=entry.get("routing_hint", "general"),
                    vector_queries=entry.get("vector_queries", []),
                )
                matched_features.append(feature)

                hint = feature.routing_hint
                routing_votes[hint] = routing_votes.get(hint, 0) + len(feature.matched_terms)
                vector_queries.extend(feature.vector_queries)
                mandatory_anchors.extend(feature.sensory_anchors[:2])

        # Determine dominant and secondary routings
        dominant_routing = "general"
        secondary_routings = []
        if routing_votes:
            sorted_votes = sorted(routing_votes.items(), key=lambda x: x[1], reverse=True)
            dominant_routing = sorted_votes[0][0]
            secondary_routings = [r for r, _ in sorted_votes[1:]]

        # Deduplicate vector queries and anchors
        dedup_queries = list(dict.fromkeys(vector_queries))
        dedup_anchors = list(dict.fromkeys(mandatory_anchors))

        return BeatAestheticProfile(
            beat_id=beat_id,
            scene_id=scene_id,
            features=matched_features,
            dominant_routing=dominant_routing,
            secondary_routings=secondary_routings,
            vector_query_paths=dedup_queries,
            mandatory_physical_anchors=dedup_anchors,
        )

    def extract_from_manifest(
        self,
        manifest_data: Dict[str, Any] | List[Dict[str, Any]]
    ) -> Dict[str, BeatAestheticProfile]:
        packets = manifest_data.get("packets", []) if isinstance(manifest_data, dict) else manifest_data
        profiles = {}
        for pkt in packets:
            p_data = pkt if isinstance(pkt, dict) else pkt.__dict__
            prof = self.extract_from_packet(p_data)
            profiles[prof.beat_id] = prof
        return profiles

    def export_ledger_json(
        self,
        profiles: Dict[str, BeatAestheticProfile],
        output_path: Optional[str | Path] = None,
    ) -> str:
        data = {
            "version": "1.0",
            "beat_count": len(profiles),
            "profiles": {b_id: p.to_dict() for b_id, p in profiles.items()},
        }
        json_str = json.dumps(data, indent=2)
        if output_path:
            Path(output_path).write_text(json_str, encoding="utf-8")
        return json_str

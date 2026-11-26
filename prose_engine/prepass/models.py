"""
Prose Engine Pre-Pass Models.
Milestone M-PE1: Aesthetic & Element Feature Ledger Extractor.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class FeatureCategory(str, Enum):
    ANATOMY_MORPH = "anatomy_morph"
    SOMATIC_FARCE = "somatic_farce"
    DOMESTIC_STAGING = "domestic_staging"
    COMEDIC_DYNAMICS = "comedic_dynamics"
    SENSORY_ATMOSPHERE = "sensory_atmosphere"


@dataclass
class AestheticFeature:
    id: str
    category: FeatureCategory
    label: str
    matched_terms: List[str] = field(default_factory=list)
    sensory_anchors: List[str] = field(default_factory=list)
    routing_hint: str = "general"
    vector_queries: List[str] = field(default_factory=list)


@dataclass
class BeatAestheticProfile:
    beat_id: str
    scene_id: str
    features: List[AestheticFeature] = field(default_factory=list)
    dominant_routing: str = "general"
    secondary_routings: List[str] = field(default_factory=list)
    vector_query_paths: List[str] = field(default_factory=list)
    mandatory_physical_anchors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "beat_id": self.beat_id,
            "scene_id": self.scene_id,
            "features": [
                {
                    "id": f.id,
                    "category": f.category.value,
                    "label": f.label,
                    "matched_terms": f.matched_terms,
                    "sensory_anchors": f.sensory_anchors,
                    "routing_hint": f.routing_hint,
                    "vector_queries": f.vector_queries,
                }
                for f in self.features
            ],
            "dominant_routing": self.dominant_routing,
            "secondary_routings": self.secondary_routings,
            "vector_query_paths": self.vector_query_paths,
            "mandatory_physical_anchors": self.mandatory_physical_anchors,
        }

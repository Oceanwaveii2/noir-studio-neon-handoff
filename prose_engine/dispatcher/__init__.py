"""
Prose Engine Dispatcher Module.
Milestone M-PE2: Segmented Sub-Corpus Dispatcher.
"""

from .book_clusters import (
    CLUSTERS,
    get_all_blocked_books,
    get_cluster_books,
)
from .router import (
    ROUTING_POLICIES,
    DispatchedCorpus,
    RoutingPolicy,
    SubCorpusDispatcher,
)

__all__ = [
    "CLUSTERS",
    "get_cluster_books",
    "get_all_blocked_books",
    "RoutingPolicy",
    "ROUTING_POLICIES",
    "DispatchedCorpus",
    "SubCorpusDispatcher",
]

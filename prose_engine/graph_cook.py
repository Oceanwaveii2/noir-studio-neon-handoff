"""Persist the structural result of evaluating a saved episode graph."""

import json
from graphlib import CycleError, TopologicalSorter

from story_graph.director import fingerprint
from story_graph.episode_timeline import encode_graph


def cook_graph(timeline, request):
    episode = request['episode']
    revision = request['revision']
    mode = request.get('mode')
    target = request.get('target')
    if type(revision) is not int or mode not in ('selected', 'downstream'):
        raise ValueError('A saved revision and graph Cook mode are required')
    if (target is not None and not isinstance(target, str)) or (mode == 'selected' and not target):
        raise ValueError('Select a graph node to check')
    with timeline._connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        current = timeline._require_active(connection, episode)
        if current['head'] != revision:
            raise ValueError('The saved graph changed. Reload it before cooking.')
        raw = connection.execute('SELECT graph FROM revisions WHERE episode=? AND revision=?',
                                 (episode, revision)).fetchone()['graph']
        graph = json.loads(raw)
        encode_graph(graph)
        nodes = {node['id']: node for node in graph['nodes']}
        if target is not None and target not in nodes:
            raise ValueError('The selected node is missing from the saved graph')
        predecessors = {node: set() for node in nodes}
        successors = {node: set() for node in nodes}
        for edge in graph['edges']:
            predecessors[edge['to']].add(edge['from'])
            successors[edge['from']].add(edge['to'])

        def reachable(start, links):
            found = set(start)
            pending = list(found)
            while pending:
                for node in links[pending.pop()] - found:
                    pending.append(node)
                    found.add(node)
            return found

        outputs = (set(nodes) if target is None else {target} if mode == 'selected'
                   else reachable({target}, successors))
        relevant = reachable(outputs, predecessors)
        try:
            order = list(TopologicalSorter({
                node: sorted(predecessors[node]) for node in sorted(relevant)
            }).static_order())
        except CycleError as error:
            raise ValueError('The selected graph contains a dependency cycle') from error
        checked = [node for node in order if not any(
            (nodes[node].get('flags') or {}).get(flag) for flag in ('bypass', 'locked')
        )]
        receipt = {'kind': 'graph-structure', 'episode': episode, 'revision': revision,
                   'graph_sha256': fingerprint(graph), 'mode': mode, 'target': target,
                   'dependency_order': order, 'checked_nodes': checked}
        receipt['id'] = fingerprint(receipt)
        connection.execute('''CREATE TABLE IF NOT EXISTS graph_cook_receipts (
                              id TEXT PRIMARY KEY, payload TEXT NOT NULL)''')
        added = connection.execute('INSERT OR IGNORE INTO graph_cook_receipts VALUES (?, ?)',
                                   (receipt['id'], json.dumps(receipt))).rowcount
        saved = connection.execute('SELECT payload FROM graph_cook_receipts WHERE id=?',
                                   (receipt['id'],)).fetchone()
        return {'status': 'CHECKED', 'receipt': json.loads(saved['payload']), 'reused': not added}

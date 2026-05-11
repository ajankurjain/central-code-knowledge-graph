"""Unit tests for the architecture analyzer's pure algorithm pieces.

We don't touch Neo4j here — `_detect_warnings` and `_cluster_name` are
purely functional. The persistence + Cypher read paths get exercised by
the integration suite (`tests/integration/`).
"""

from __future__ import annotations

import networkx as nx

from ckg.services.architecture import (
    DEFAULT_FAN_IN_THRESHOLD,
    DEFAULT_FAN_OUT_THRESHOLD,
    _cluster_name,
    _detect_warnings,
)


def test_cluster_name_picks_longest_common_prefix():
    members = {"src/foo/a.py", "src/foo/b.py", "src/foo/sub/c.py"}
    assert _cluster_name(members) == "src/foo"


def test_cluster_name_no_common_prefix_falls_back_to_shortest():
    members = {"src/a.py", "tests/b.py"}
    # No common prefix → fall back to shortest member
    assert _cluster_name(members) in members


def test_cluster_name_singleton():
    assert _cluster_name({"src/x.py"}) == "src/x.py"


def test_cluster_name_empty():
    assert _cluster_name(set()) == "(empty)"


def test_detect_warnings_finds_cyclic_dependency():
    # Build a 3-file cycle: a -> b -> c -> a
    dg = nx.DiGraph()
    dg.add_edge("a.py", "b.py")
    dg.add_edge("b.py", "c.py")
    dg.add_edge("c.py", "a.py")
    warnings = _detect_warnings(
        repo_id="r", directed=dg, clusters=[],
        cluster_metrics={}, cluster_edges={},
        file_fanin={}, file_fanout={},
    )
    kinds = {w["kind"] for w in warnings}
    assert "cyclic_dependency" in kinds


def test_detect_warnings_no_cycle_when_acyclic():
    dg = nx.DiGraph()
    dg.add_edge("a.py", "b.py")
    dg.add_edge("b.py", "c.py")
    warnings = _detect_warnings(
        repo_id="r", directed=dg, clusters=[],
        cluster_metrics={}, cluster_edges={},
        file_fanin={}, file_fanout={},
    )
    assert all(w["kind"] != "cyclic_dependency" for w in warnings)


def test_detect_warnings_high_fan_in():
    fan_in = {"hub.py": DEFAULT_FAN_IN_THRESHOLD + 5}
    warnings = _detect_warnings(
        repo_id="r", directed=nx.DiGraph(), clusters=[],
        cluster_metrics={}, cluster_edges={},
        file_fanin=fan_in, file_fanout={},
    )
    hub = [w for w in warnings if w["kind"] == "high_fan_in"]
    assert len(hub) == 1
    assert hub[0]["target_id"] == "hub.py"
    assert hub[0]["severity"] == "medium"


def test_detect_warnings_high_fan_out():
    fan_out = {"sink.py": DEFAULT_FAN_OUT_THRESHOLD + 1}
    warnings = _detect_warnings(
        repo_id="r", directed=nx.DiGraph(), clusters=[],
        cluster_metrics={}, cluster_edges={},
        file_fanin={}, file_fanout=fan_out,
    )
    kinds = {w["kind"] for w in warnings}
    assert "high_fan_out" in kinds


def test_detect_warnings_sdp_violation():
    # Cluster 0 is very stable (I=0.1), depends on cluster 1 which is unstable (I=0.9)
    clusters = [
        {"id": 0, "name": "core", "files": ["core/a.py"]},
        {"id": 1, "name": "ui", "files": ["ui/b.py"]},
    ]
    metrics = {
        0: {"instability": 0.1, "cohesion": 1.0, "fan_in": 5, "fan_out": 1},
        1: {"instability": 0.9, "cohesion": 1.0, "fan_in": 1, "fan_out": 9},
    }
    edges = {(0, 1): {"weight": 1, "files": 1}}
    warnings = _detect_warnings(
        repo_id="r", directed=nx.DiGraph(), clusters=clusters,
        cluster_metrics=metrics, cluster_edges=edges,
        file_fanin={}, file_fanout={},
    )
    sdp = [w for w in warnings if w["kind"] == "sdp_violation"]
    assert sdp
    assert "violates SDP" in sdp[0]["message"]


def test_detect_warnings_low_cohesion():
    clusters = [{"id": 0, "name": "mixed", "files": ["a.py", "b.py", "c.py"]}]
    metrics = {0: {"instability": 0.5, "cohesion": 0.2, "fan_in": 3, "fan_out": 3}}
    warnings = _detect_warnings(
        repo_id="r", directed=nx.DiGraph(), clusters=clusters,
        cluster_metrics=metrics, cluster_edges={},
        file_fanin={}, file_fanout={},
    )
    lo = [w for w in warnings if w["kind"] == "low_cohesion"]
    assert lo
    assert lo[0]["severity"] == "low"

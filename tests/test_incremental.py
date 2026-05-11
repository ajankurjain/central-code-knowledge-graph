"""Unit-level test of the incremental-diff classification logic.

We don't spin up Neo4j here — we feed `_run_incremental`-style inputs to the
classification step by mocking. A proper end-to-end test lives in
`tests/integration/` and requires `docker compose up` first.
"""

from __future__ import annotations


def _classify(on_disk: dict[str, str], existing: dict[str, str]) -> dict[str, list[str]]:
    """Same three-way diff as in `_run_incremental`. Kept here as a pure
    function so it's testable without Neo4j."""
    added, changed, unchanged, removed = [], [], [], []
    for path, sha in on_disk.items():
        old = existing.get(path)
        if old is None:
            added.append(path)
        elif old == sha:
            unchanged.append(path)
        else:
            changed.append(path)
    for path in existing:
        if path not in on_disk:
            removed.append(path)
    return {"added": added, "changed": changed, "unchanged": unchanged, "removed": removed}


def test_classify_added_changed_unchanged_removed():
    existing = {"a.py": "sha_a", "b.py": "sha_b_old", "c.py": "sha_c"}
    on_disk = {
        "a.py": "sha_a",          # unchanged
        "b.py": "sha_b_new",      # changed
        "d.py": "sha_d",          # added
        # c.py removed
    }
    result = _classify(on_disk, existing)
    assert result["added"] == ["d.py"]
    assert result["changed"] == ["b.py"]
    assert result["unchanged"] == ["a.py"]
    assert result["removed"] == ["c.py"]


def test_classify_empty_existing_treats_everything_as_added():
    on_disk = {"a.py": "x", "b.py": "y"}
    result = _classify(on_disk, {})
    assert set(result["added"]) == {"a.py", "b.py"}
    assert result["changed"] == []
    assert result["unchanged"] == []
    assert result["removed"] == []


def test_classify_empty_on_disk_treats_everything_as_removed():
    existing = {"a.py": "x", "b.py": "y"}
    result = _classify({}, existing)
    assert result["added"] == []
    assert result["changed"] == []
    assert result["unchanged"] == []
    assert set(result["removed"]) == {"a.py", "b.py"}


def test_ingest_stats_to_dict_has_phase2_keys():
    from ckg.services.ingest import IngestStats

    s = IngestStats(mode="incremental")
    d = s.to_dict()
    for key in ("mode", "files_added", "files_changed", "files_removed", "files_unchanged"):
        assert key in d, f"missing {key} in IngestStats.to_dict()"

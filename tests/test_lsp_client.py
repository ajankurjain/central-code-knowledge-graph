"""Unit tests for the generic LSP client's framing + parsing helpers.

We don't spawn an actual LSP here — just exercise the byte-level pieces.
"""

from __future__ import annotations

import io
from pathlib import Path

from ckg.lsp.client import _parse_locations, _path_to_uri, _read_message, _uri_to_path


def test_path_to_uri_round_trip(tmp_path: Path):
    p = tmp_path / "a" / "b.py"
    p.parent.mkdir(parents=True)
    p.write_text("x")
    uri = _path_to_uri(p)
    assert uri.startswith("file://")
    assert _uri_to_path(uri) == str(p.resolve())


def test_read_message_frames_a_single_payload():
    body = b'{"jsonrpc":"2.0","id":1,"result":{"ok":true}}'
    header = f"Content-Length: {len(body)}\r\n\r\n".encode()
    stream = io.BufferedReader(io.BytesIO(header + body))
    msg = _read_message(stream)
    assert msg == {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}


def test_read_message_returns_none_on_empty_stream():
    stream = io.BufferedReader(io.BytesIO(b""))
    assert _read_message(stream) is None


def test_parse_locations_filters_external_paths(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    inside = repo / "src" / "x.py"
    inside.parent.mkdir()
    inside.write_text("")
    outside = tmp_path / "stdlib" / "json.py"
    outside.parent.mkdir()
    outside.write_text("")

    result = [
        {"uri": _path_to_uri(inside), "range": {"start": {"line": 4, "character": 2}}},
        {"uri": _path_to_uri(outside), "range": {"start": {"line": 0, "character": 0}}},
    ]
    locs = _parse_locations(result, repo_root=repo)
    assert len(locs) == 1
    assert locs[0].file_path == "src/x.py"
    assert locs[0].line == 5          # 0-based → 1-based
    assert locs[0].character == 2


def test_parse_locations_handles_target_uri_link_form(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    f = repo / "src" / "y.py"
    f.parent.mkdir()
    f.write_text("")
    result = [{
        "targetUri": _path_to_uri(f),
        "targetSelectionRange": {"start": {"line": 9, "character": 4}},
    }]
    locs = _parse_locations(result, repo_root=repo)
    assert len(locs) == 1
    assert locs[0].line == 10

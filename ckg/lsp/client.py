"""Generic JSON-RPC over stdio LSP client.

Implements just enough of the protocol to drive a definition lookup loop:
- initialize / initialized handshake
- workspace folders
- textDocument/didOpen + didClose
- textDocument/definition (returns a single Location or list of Locations)
- shutdown / exit

Spec: https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/
"""

from __future__ import annotations

import json
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from queue import Queue
from typing import Any
from urllib.parse import unquote, urlparse

from ckg.logging import get_logger
from ckg.lsp.base import ResolvedLocation

log = get_logger(__name__)


@dataclass
class _Pending:
    method: str
    q: "Queue[dict]"


class LspClient:
    """One short-lived LSP session per (adapter, repo)."""

    def __init__(self, cmd: list[str], repo_root: Path, language_id: str,
                 init_options: dict | None = None, request_timeout: float = 10.0):
        self.repo_root = repo_root.resolve()
        self.language_id = language_id
        self.request_timeout = request_timeout
        self._next_id = 1
        self._pending: dict[int, _Pending] = {}
        self._proc = subprocess.Popen(
            cmd, cwd=str(self.repo_root),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self._stop = threading.Event()
        self._reader = threading.Thread(target=self._read_loop, name="lsp-reader", daemon=True)
        self._reader.start()
        self._initialize(init_options)

    # ── Public API ──────────────────────────────────────────────────────────

    def did_open(self, path: Path, text: str, version: int = 1) -> None:
        self._notify("textDocument/didOpen", {
            "textDocument": {
                "uri": _path_to_uri(path),
                "languageId": self.language_id,
                "version": version,
                "text": text,
            }
        })

    def did_close(self, path: Path) -> None:
        self._notify("textDocument/didClose", {
            "textDocument": {"uri": _path_to_uri(path)},
        })

    def definition(self, path: Path, line: int, character: int) -> list[ResolvedLocation]:
        """1-based line, 0-based character — LSP wants 0-based for both, so
        we subtract 1 from `line` at the boundary."""
        params = {
            "textDocument": {"uri": _path_to_uri(path)},
            "position": {"line": max(0, line - 1), "character": character},
        }
        result = self._request("textDocument/definition", params)
        return _parse_locations(result, repo_root=self.repo_root)

    def close(self) -> None:
        try:
            self._request("shutdown", None, timeout=2.0)
        except Exception:  # noqa: BLE001
            pass
        try:
            self._notify("exit", None)
        except Exception:  # noqa: BLE001
            pass
        self._stop.set()
        try:
            self._proc.terminate()
            self._proc.wait(timeout=3.0)
        except Exception:  # noqa: BLE001
            self._proc.kill()

    # ── Internals ───────────────────────────────────────────────────────────

    def _initialize(self, init_options: dict | None) -> None:
        params = {
            "processId": None,
            "rootUri": _path_to_uri(self.repo_root),
            "workspaceFolders": [
                {"uri": _path_to_uri(self.repo_root), "name": self.repo_root.name}
            ],
            "capabilities": {
                "textDocument": {
                    "definition": {"linkSupport": False},
                    "synchronization": {"didSave": False, "willSave": False},
                },
                "workspace": {"workspaceFolders": True},
            },
            "initializationOptions": init_options or {},
        }
        self._request("initialize", params, timeout=30.0)
        self._notify("initialized", {})

    def _next_request_id(self) -> int:
        i = self._next_id
        self._next_id += 1
        return i

    def _request(self, method: str, params: Any, timeout: float | None = None) -> Any:
        rid = self._next_request_id()
        q: "Queue[dict]" = Queue(maxsize=1)
        self._pending[rid] = _Pending(method=method, q=q)
        self._write({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        try:
            msg = q.get(timeout=timeout or self.request_timeout)
        except Exception as exc:
            self._pending.pop(rid, None)
            raise TimeoutError(f"LSP {method} timed out") from exc
        if "error" in msg:
            raise RuntimeError(f"LSP {method} error: {msg['error']}")
        return msg.get("result")

    def _notify(self, method: str, params: Any) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def _write(self, obj: dict) -> None:
        payload = json.dumps(obj).encode("utf-8")
        header = f"Content-Length: {len(payload)}\r\n\r\n".encode()
        assert self._proc.stdin is not None
        self._proc.stdin.write(header + payload)
        self._proc.stdin.flush()

    def _read_loop(self) -> None:
        assert self._proc.stdout is not None
        while not self._stop.is_set():
            try:
                msg = _read_message(self._proc.stdout)
            except Exception as exc:
                if not self._stop.is_set():
                    log.warning("lsp_read_failed", error=str(exc))
                return
            if msg is None:
                return
            # Server-initiated request → respond null so the server doesn't hang.
            # We only care about responses to *our* requests + notifications we
            # can ignore.
            if "id" in msg and "method" in msg:
                self._write({"jsonrpc": "2.0", "id": msg["id"], "result": None})
                continue
            if "id" in msg:
                rid = msg["id"]
                pending = self._pending.pop(rid, None)
                if pending is not None:
                    pending.q.put(msg)
                continue
            # Notifications from server: ignore (logMessage, publishDiagnostics, etc.)


# ── Framing helpers ─────────────────────────────────────────────────────────


def _read_message(stream) -> dict | None:
    header = b""
    while True:
        line = stream.readline()
        if not line:
            return None
        header += line
        if header.endswith(b"\r\n\r\n"):
            break
    length = 0
    for part in header.split(b"\r\n"):
        if part.lower().startswith(b"content-length:"):
            length = int(part.split(b":", 1)[1].strip())
            break
    if length <= 0:
        return None
    body = b""
    while len(body) < length:
        chunk = stream.read(length - len(body))
        if not chunk:
            return None
        body += chunk
    return json.loads(body.decode("utf-8"))


def _path_to_uri(path: Path) -> str:
    return path.resolve().as_uri()


def _uri_to_path(uri: str) -> str:
    parsed = urlparse(uri)
    return unquote(parsed.path)


def _parse_locations(result: Any, *, repo_root: Path) -> list[ResolvedLocation]:
    if result is None:
        return []
    items = result if isinstance(result, list) else [result]
    out: list[ResolvedLocation] = []
    rr = str(repo_root.resolve())
    for item in items:
        if not isinstance(item, dict):
            continue
        uri = item.get("uri") or item.get("targetUri")
        rng = item.get("range") or item.get("targetSelectionRange") or item.get("targetRange")
        if not uri or not rng:
            continue
        abs_path = _uri_to_path(uri)
        # Skip results outside the repo (e.g. stdlib / dependencies)
        if not abs_path.startswith(rr):
            continue
        rel = abs_path[len(rr):].lstrip("/")
        start = rng.get("start") or {}
        out.append(ResolvedLocation(
            file_path=rel,
            line=int(start.get("line", 0)) + 1,
            character=int(start.get("character", 0)),
        ))
    return out

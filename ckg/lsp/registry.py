"""Language → LSP adapter registry."""

from __future__ import annotations

from ckg.lsp.base import LspAdapter
from ckg.lsp.pyright import PyrightAdapter

_ADAPTERS: dict[str, type[LspAdapter]] = {
    "python": PyrightAdapter,
    # Stubs to add in future phases:
    # "rust":       RustAnalyzerAdapter,
    # "go":         GoplsAdapter,
    # "typescript": TsServerAdapter,
    # "java":       JdtlsAdapter,
}


def get_adapter(language: str) -> LspAdapter | None:
    cls = _ADAPTERS.get(language)
    if cls is None:
        return None
    inst = cls()
    return inst if inst.is_available() else None


def available_adapters() -> list[LspAdapter]:
    out: list[LspAdapter] = []
    for cls in _ADAPTERS.values():
        inst = cls()
        if inst.is_available():
            out.append(inst)
    return out

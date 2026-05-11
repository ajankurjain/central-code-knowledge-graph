"""Pyright adapter — `pyright-langserver --stdio`.

Install:
    npm install -g pyright

Or per-project:
    pip install pyright

Then `which pyright-langserver` should return a path.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PyrightAdapter:
    language: str = "python"

    def is_available(self) -> bool:
        return shutil.which("pyright-langserver") is not None

    def server_command(self, repo_root: Path) -> list[str]:
        return ["pyright-langserver", "--stdio"]

    def file_uri_extensions(self) -> tuple[str, ...]:
        return (".py", ".pyi")

    def language_id(self) -> str:
        return "python"

    def initialization_options(self) -> dict | None:
        return {
            "settings": {
                "python": {
                    "analysis": {
                        # We're only asking for go-to-definition; turn down the
                        # rest to keep pyright responsive on large workspaces.
                        "diagnosticMode": "openFilesOnly",
                        "typeCheckingMode": "off",
                    }
                }
            }
        }

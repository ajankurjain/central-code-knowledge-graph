"""Central code knowledge graph."""

# Read the version from the installed distribution metadata so we don't
# have two sources of truth (pyproject.toml + this constant) drifting
# across releases. Falls back to a hard-coded value only when the
# package isn't installed (e.g. running from an unpacked tarball during
# CI bootstrap).
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

try:
    __version__ = _pkg_version("central-code-knowledge-graph")
except PackageNotFoundError:  # pragma: no cover — only hit pre-install
    __version__ = "0.0.0+local"

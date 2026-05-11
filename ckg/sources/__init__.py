"""Bulk-source discovery providers (GitHub, GitLab, Bitbucket, manifest)."""

from ckg.sources.base import DiscoveredRepo, SourceProvider, SourceSpec
from ckg.sources.detect import detect_source_kind
from ckg.sources.registry import get_provider

__all__ = [
    "DiscoveredRepo",
    "SourceProvider",
    "SourceSpec",
    "detect_source_kind",
    "get_provider",
]

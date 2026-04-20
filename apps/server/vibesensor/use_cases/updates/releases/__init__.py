"""GitHub release fetch and validation helpers for updater workflows."""

from __future__ import annotations

from importlib import import_module

_EXPORTS = (
    ("DOWNLOAD_CHUNK_BYTES", ".github_api"),
    ("GitHubApiClient", ".github_api"),
    ("GitHubRelease", ".models"),
    ("GitHubReleaseAsset", ".models"),
    ("ReleaseFetcherConfig", ".models"),
    ("ReleaseInfo", ".models"),
    ("ServerReleaseFetcher", ".release_fetcher"),
    ("github_api_headers", ".github_api"),
    ("release_validation", ".release_validation"),
    ("resolve_release_fetcher_config", ".models"),
    ("select_update_release", ".version_policy"),
    ("validate_https_url", ".github_api"),
)

_EXPORT_MODULES = dict(_EXPORTS)
__all__ = [name for name, _module_name in _EXPORTS]


def __getattr__(name: str) -> object:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name, __name__)
    value = module if name == "release_validation" else getattr(module, name)
    globals()[name] = value
    return value

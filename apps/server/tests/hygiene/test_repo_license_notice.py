"""Guard that the public repo has explicit reuse terms."""

from __future__ import annotations

from tests._paths import REPO_ROOT

_LICENSE = REPO_ROOT / "LICENSE"
_README = REPO_ROOT / "README.md"
_STANDARD_LICENSE_MARKERS = (
    "mit license",
    "apache license",
    "gnu general public license",
    "bsd 2-clause license",
    "bsd 3-clause license",
    "mozilla public license",
)
_UNLICENSED_NOTICE_MARKERS = (
    "not currently distributed under an open-source license",
    "all rights reserved",
    "no additional permission is granted",
)


def _has_standard_license(text: str) -> bool:
    normalized = " ".join(text.lower().split())
    return any(marker in normalized for marker in _STANDARD_LICENSE_MARKERS)


def _has_explicit_unlicensed_notice(text: str) -> bool:
    normalized = " ".join(text.lower().split())
    return all(marker in normalized for marker in _UNLICENSED_NOTICE_MARKERS)


def test_repo_has_standard_license_or_explicit_unlicensed_notice() -> None:
    assert _LICENSE.exists(), "Public repos must have LICENSE or explicit unlicensed notice"

    license_text = _LICENSE.read_text(encoding="utf-8")
    assert _has_standard_license(license_text) or _has_explicit_unlicensed_notice(license_text), (
        "LICENSE must be a standard license or explicit unlicensed notice"
    )


def test_readme_links_reuse_terms() -> None:
    readme = _README.read_text(encoding="utf-8")

    assert "## License" in readme
    assert "[LICENSE](LICENSE)" in readme

"""Stage 0: version coherence for the canonical v0.32.0 RC.

Guards that the CLI/dist version, the pyproject version, and the
types-dependency floor agree, and that this is the 0.32 line. Robust
to a coordinated patch bump (it asserts the dist and pyproject *agree*
rather than hardcoding a full literal), while pinning the RC minor so
a stray version drift is caught.
"""
from __future__ import annotations

import importlib.metadata
import tomllib
from pathlib import Path

# tests/ -> packages/chimera-memory/
_PKG_ROOT = Path(__file__).resolve().parents[1]
# tests/ -> packages/chimera-memory/ -> packages/ -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _pyproject() -> dict:
    return tomllib.loads((_PKG_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_dist_version_matches_pyproject() -> None:
    dist = importlib.metadata.version("chimera-memory")
    proj = _pyproject()["project"]["version"]
    assert dist == proj, f"installed dist version {dist!r} != pyproject {proj!r}"


def test_canonical_is_the_0_32_line() -> None:
    proj = _pyproject()["project"]["version"]
    assert proj.startswith("0.32"), f"expected the 0.32 RC line, got {proj!r}"


def test_types_dependency_floor_coheres() -> None:
    deps = _pyproject()["project"]["dependencies"]
    matches = [d for d in deps if "chimera-memory-types" in d]
    assert matches, "chimera-memory-types must be a declared dependency"
    assert any("0.32" in d for d in matches), (
        f"types dependency floor should track the 0.32 line, got {matches!r}"
    )


def test_release_note_version_coheres() -> None:
    # The release note for the pyproject version must exist and name it, tying
    # the release-note version to the package/dist version. Non-brittle: it
    # checks file presence and that the version string appears, not exact prose.
    proj = _pyproject()["project"]["version"]
    note = _REPO_ROOT / "docs" / "releases" / f"v{proj}.md"
    assert note.exists(), f"missing release note for v{proj}: {note}"
    assert proj in note.read_text(encoding="utf-8"), (
        f"release note {note.name} does not name version {proj!r}"
    )

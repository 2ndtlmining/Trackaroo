"""release.py: cut a version from CHANGELOG.md's Unreleased section."""
import json
import re
from datetime import date
from pathlib import Path

import pytest

import release

ROOT = Path(__file__).resolve().parents[1]

CHANGELOG = """# Changelog

Intro.

## Unreleased

### Added
- New thing (#1)

## 0.3.0 — 2026-10-02

- Old thing
"""

PACKAGE = '{\n\t"name": "web",\n\t"version": "0.3.0",\n\t"dependencies": {\n\t\t"x": "^1.0.0"\n\t}\n}\n'

LOCK = (
    '{\n\t"name": "web",\n\t"version": "0.3.0",\n\t"packages": {\n\t\t"": {\n'
    '\t\t\t"name": "web",\n\t\t\t"version": "0.3.0"\n\t\t},\n'
    '\t\t"node_modules/x": {\n\t\t\t"version": "0.3.0"\n\t\t}\n\t}\n}\n'
)


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "web").mkdir()
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
    (tmp_path / "web" / "package.json").write_text(PACKAGE, encoding="utf-8")
    (tmp_path / "web" / "package-lock.json").write_text(LOCK, encoding="utf-8")
    return tmp_path


def test_moves_unreleased_into_a_dated_release(repo):
    release.release("0.4.0", root=repo, today=date(2026, 10, 3))
    text = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## Unreleased\n\n## 0.4.0 — 2026-10-03\n\n### Added\n- New thing (#1)\n\n## 0.3.0" in text


def test_bumps_package_and_lockfile_but_not_dependencies(repo):
    release.release("0.4.0", root=repo, today=date(2026, 10, 3))
    pkg = json.loads((repo / "web" / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((repo / "web" / "package-lock.json").read_text(encoding="utf-8"))
    assert pkg["version"] == "0.4.0"
    assert lock["version"] == "0.4.0"
    assert lock["packages"][""]["version"] == "0.4.0"
    # A dependency that happens to share the old version number is untouched.
    assert lock["packages"]["node_modules/x"]["version"] == "0.3.0"
    # Formatting (tabs) survives.
    assert '\t"version": "0.4.0"' in (repo / "web" / "package.json").read_text(encoding="utf-8")


@pytest.mark.parametrize("bad", ["0.4", "v0.4.0", "0.4.0-beta", "abc"])
def test_rejects_a_malformed_version(repo, bad):
    with pytest.raises(release.ReleaseError, match="X.Y.Z"):
        release.release(bad, root=repo, today=date(2026, 10, 3))


@pytest.mark.parametrize("old", ["0.3.0", "0.2.9"])
def test_rejects_a_version_that_does_not_go_up(repo, old):
    with pytest.raises(release.ReleaseError, match="greater than 0.3.0"):
        release.release(old, root=repo, today=date(2026, 10, 3))


def test_rejects_an_empty_unreleased_section(repo):
    (repo / "CHANGELOG.md").write_text(
        CHANGELOG.replace("### Added\n- New thing (#1)\n\n", ""), encoding="utf-8"
    )
    with pytest.raises(release.ReleaseError, match="Unreleased"):
        release.release("0.4.0", root=repo, today=date(2026, 10, 3))
    # Nothing was written.
    assert '"version": "0.3.0"' in (repo / "web" / "package.json").read_text(encoding="utf-8")


def test_keeps_crlf_line_endings(repo):
    path = repo / "CHANGELOG.md"
    path.write_bytes(CHANGELOG.replace("\n", "\r\n").encode("utf-8"))
    release.release("0.4.0", root=repo, today=date(2026, 10, 3))
    raw = path.read_bytes()
    assert b"## 0.4.0 \xe2\x80\x94 2026-10-03\r\n" in raw
    assert b"\n" not in raw.replace(b"\r\n", b"")


def test_repo_changelog_matches_package_version():
    """The shipped CHANGELOG's newest release is the version package.json declares."""
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    newest = re.search(r"^## (\d+\.\d+\.\d+)\b", text, re.M)
    pkg = json.loads((ROOT / "web" / "package.json").read_text(encoding="utf-8"))
    assert newest and newest.group(1) == pkg["version"]

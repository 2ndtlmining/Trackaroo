"""Cut a release: move CHANGELOG.md's Unreleased notes into a dated version.

    python release.py 0.4.0

Rewrites CHANGELOG.md (a fresh empty "## Unreleased" stays on top) and bumps
the version in web/package.json and web/package-lock.json. web/package.json is
the single source the site reads (footer, /changelog, /healthz `release`).

It does not commit, tag or push. Afterwards: commit, merge, then tag the merge
commit (`git tag -a vX.Y.Z -m "vX.Y.Z" <sha> && git push origin vX.Y.Z`).
"""
import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Optional, Tuple

ROOT = Path(__file__).resolve().parent
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
UNRELEASED = "## Unreleased"


class ReleaseError(Exception):
    pass


def _parse(version: str) -> Tuple[int, ...]:
    return tuple(int(p) for p in version.split("."))


def _read(path: Path) -> Tuple[str, str]:
    """Text with LF line endings, plus the file's original newline."""
    raw = path.read_bytes().decode("utf-8")
    newline = "\r\n" if "\r\n" in raw else "\n"
    return raw.replace("\r\n", "\n"), newline


def _write(path: Path, text: str, newline: str) -> None:
    path.write_bytes(text.replace("\n", newline).encode("utf-8"))


def _bump_json_versions(text: str, old: str, new: str, count: int) -> str:
    """Replace the first `count` top-level-ish "version": "<old>" entries.

    package.json has one; package-lock.json has the root and packages[""].
    Dependencies further down that share the number are left alone.
    """
    pattern = re.compile(r'("version":\s*")' + re.escape(old) + '"')
    result, n = pattern.subn(r"\g<1>" + new + '"', text, count=count)
    if n != count:
        raise ReleaseError(f"expected {count} version field(s) of {old}, found {n}")
    return result


def release(version: str, root: Path = ROOT, today: Optional[date] = None) -> None:
    if not SEMVER.match(version):
        raise ReleaseError(f"version must be X.Y.Z, got {version!r}")

    changelog_path = root / "CHANGELOG.md"
    package_path = root / "web" / "package.json"
    lock_path = root / "web" / "package-lock.json"

    current = json.loads(package_path.read_text(encoding="utf-8"))["version"]
    if _parse(version) <= _parse(current):
        raise ReleaseError(f"version must be greater than {current}, got {version}")

    changelog, cl_nl = _read(changelog_path)
    start = changelog.find(UNRELEASED + "\n")
    if start < 0:
        raise ReleaseError("CHANGELOG.md has no '## Unreleased' heading")
    body_start = start + len(UNRELEASED) + 1
    nxt = changelog.find("\n## ", body_start)
    body_end = nxt + 1 if nxt >= 0 else len(changelog)
    notes = changelog[body_start:body_end].strip("\n")
    if not notes.strip():
        raise ReleaseError("the Unreleased section is empty: nothing to release")

    stamp = (today or date.today()).isoformat()
    new_changelog = (
        changelog[:start]
        + f"{UNRELEASED}\n\n## {version} — {stamp}\n\n{notes}\n\n"
        + changelog[body_end:]
    )

    package, pkg_nl = _read(package_path)
    lock, lock_nl = _read(lock_path)
    new_package = _bump_json_versions(package, current, version, 1)
    new_lock = _bump_json_versions(lock, current, version, 2)

    # Every check passed: write all three.
    _write(changelog_path, new_changelog, cl_nl)
    _write(package_path, new_package, pkg_nl)
    _write(lock_path, new_lock, lock_nl)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version", help="the new version, X.Y.Z")
    args = parser.parse_args(argv)
    try:
        release(args.version)
    except ReleaseError as e:
        print(f"release: {e}", file=sys.stderr)
        return 1
    print(f"Released {args.version} in CHANGELOG.md and web/package.json.")
    print(f"Next: commit, merge, then tag the merge commit v{args.version} and push the tag.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

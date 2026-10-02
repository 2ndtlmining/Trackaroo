"""Cut a release: move CHANGELOG.md's Unreleased notes into a dated version.

    python release.py 0.4.0

Rewrites CHANGELOG.md (a fresh empty "## Unreleased" stays on top) and bumps
the version in web/package.json and web/package-lock.json. web/package.json is
the single source the site reads (footer, /changelog, /healthz `release`).

All three files are written or none is: the repo lives in OneDrive, where a
locked file is a realistic failure halfway through.

It does not commit, tag or push. Afterwards: commit, merge, then tag the merge
commit (`git tag -a vX.Y.Z -m "vX.Y.Z" <sha> && git push origin vX.Y.Z`).
"""
import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path
from typing import Dict, Optional, Tuple

ROOT = Path(__file__).resolve().parent
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
UNRELEASED_RE = re.compile(r"^## Unreleased[ \t]*$", re.M)
NEXT_RELEASE_RE = re.compile(r"^## ", re.M)
BULLET_RE = re.compile(r"^\s*[-*] \S", re.M)
TMP_SUFFIX = ".release-tmp"


class ReleaseError(Exception):
    pass


def _parse(version: str, what: str) -> Tuple[int, ...]:
    if not SEMVER.match(version):
        raise ReleaseError(f"{what} must be X.Y.Z, got {version!r}")
    return tuple(int(p) for p in version.split("."))


def _read(path: Path) -> Tuple[str, str]:
    """Text with LF line endings, plus the file's original newline."""
    raw = path.read_bytes().decode("utf-8")
    newline = "\r\n" if "\r\n" in raw else "\n"
    return raw.replace("\r\n", "\n"), newline


def _bump_json_versions(text: str, old: str, new: str, count: int) -> str:
    """Replace the first `count` "version": "<old>" entries.

    package.json has one; package-lock.json has the root and packages[""],
    which come first in the file. The caller has already checked both hold
    `old`, so a dependency further down sharing the number is never reached.
    """
    pattern = re.compile(r'("version":\s*")' + re.escape(old) + '"')
    result, n = pattern.subn(r"\g<1>" + new + '"', text, count=count)
    if n != count:
        raise ReleaseError(f"expected {count} version field(s) of {old}, found {n}")
    return result


def _write_all(files: Dict[Path, Tuple[str, str]]) -> None:
    """Write every file or none: temp siblings first, then swap them in.

    If a swap fails, the files already swapped are put back.
    """
    originals = {path: path.read_bytes() for path in files}
    tmps = {}
    try:
        for path, (text, newline) in files.items():
            tmp = path.with_name(path.name + TMP_SUFFIX)
            tmp.write_bytes(text.replace("\n", newline).encode("utf-8"))
            tmps[path] = tmp
        done = []
        try:
            for path, tmp in tmps.items():
                os.replace(tmp, path)
                done.append(path)
        except OSError:
            for path in done:
                path.write_bytes(originals[path])
            raise
    except OSError as e:
        raise ReleaseError(f"could not write the release, nothing changed: {e}") from e
    finally:
        for tmp in tmps.values():
            if tmp.exists():
                tmp.unlink()


def release(version: str, root: Optional[Path] = None, today: Optional[date] = None) -> None:
    root = root or ROOT
    new = _parse(version, "version")

    changelog_path = root / "CHANGELOG.md"
    package_path = root / "web" / "package.json"
    lock_path = root / "web" / "package-lock.json"

    package, pkg_nl = _read(package_path)
    lock, lock_nl = _read(lock_path)
    current = json.loads(package)["version"]
    if new <= _parse(current, "web/package.json version"):
        raise ReleaseError(f"version must be greater than {current}, got {version}")
    lock_json = json.loads(lock)
    lock_versions = (lock_json.get("version"), lock_json.get("packages", {}).get("", {}).get("version"))
    if lock_versions != (current, current):
        raise ReleaseError(
            f"web/package-lock.json is out of step with package.json ({current}): "
            f"found {lock_versions}; run npm install in web/ first"
        )

    changelog, cl_nl = _read(changelog_path)
    heading = UNRELEASED_RE.search(changelog)
    if not heading:
        raise ReleaseError("CHANGELOG.md has no '## Unreleased' heading")
    body_start = heading.end()
    nxt = NEXT_RELEASE_RE.search(changelog, body_start)
    body_end = nxt.start() if nxt else len(changelog)
    notes = changelog[body_start:body_end].strip("\n")
    if not BULLET_RE.search(notes):
        raise ReleaseError("the Unreleased section has no bullet points: nothing to release")

    stamp = (today or date.today()).isoformat()
    rest = changelog[body_end:]
    new_changelog = (
        changelog[: heading.start()]
        + f"## Unreleased\n\n## {version} — {stamp}\n\n{notes}\n"
        + ("\n" + rest if rest else "")
    )

    _write_all({
        changelog_path: (new_changelog, cl_nl),
        package_path: (_bump_json_versions(package, current, version, 1), pkg_nl),
        lock_path: (_bump_json_versions(lock, current, version, 2), lock_nl),
    })


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version", help="the new version, X.Y.Z")
    args = parser.parse_args(argv)
    try:
        release(args.version)
    except (ReleaseError, OSError, KeyError, ValueError) as e:
        print(f"release: {e}", file=sys.stderr)
        return 1
    print(f"Released {args.version} in CHANGELOG.md and web/package.json.")
    print(f"Next: commit, merge, then tag the merge commit v{args.version} and push the tag.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

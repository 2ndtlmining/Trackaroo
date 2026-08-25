"""Shell scripts must reach the working tree as LF or the image cannot start.

Git stores `deploy/*.sh` as LF and always has -- the blob for
entrypoint-single.sh is unchanged since it was added. The damage happens on
*checkout*: Git for Windows ships `core.autocrlf=true` at system scope, so
before `.gitattributes` existed every Windows clone materialised these scripts
with CRLF. `docker build` COPYs the working-tree file, so the CR rode into the
image and the shebang became `#!/bin/sh` + CR. Linux then hunts for an
interpreter literally named "/bin/sh<CR>", fails, and reports the ENOENT
against the *script*:

    [FATAL tini (7)] exec /usr/local/bin/trackaroo-entrypoint failed:
    No such file or directory

which reads as a missing COPY and sends you looking in the wrong place.

Verified by clean clone: at the parent commit entrypoint-single.sh arrives with
CR=162; with `.gitattributes` present it arrives with CR=0.

This test guards the *working tree* deliberately -- that is the layer that
breaks and the layer `docker build` reads. Two other guards back it up:
`.gitattributes` pins `*.sh` to eol=lf, and the Dockerfile strips CRs after
COPY and runs `sh -n` on each script.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _tracked_shell_scripts() -> list[Path]:
    """Every .sh file git knows about, so a new one is covered automatically."""
    result = subprocess.run(
        ["git", "ls-files", "*.sh"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [REPO_ROOT / line for line in result.stdout.split() if line]


def test_shell_scripts_are_tracked():
    """Guard the guard: an empty list would make every test below vacuous."""
    scripts = _tracked_shell_scripts()
    assert scripts, "no tracked *.sh files found -- is git available?"


@pytest.mark.parametrize("script", _tracked_shell_scripts(), ids=lambda p: p.name)
def test_shell_script_has_no_carriage_returns(script: Path):
    raw = script.read_bytes()
    offenders = [
        i + 1 for i, line in enumerate(raw.split(b"\n")) if line.endswith(b"\r")
    ]
    assert not offenders, (
        f"{script.relative_to(REPO_ROOT)} has CRLF line endings on "
        f"{len(offenders)} line(s) (first: line {offenders[0] if offenders else '-'}). "
        "The container cannot exec a script whose shebang ends in \\r. "
        "Fix with: git add --renormalize <file>"
    )


@pytest.mark.parametrize("script", _tracked_shell_scripts(), ids=lambda p: p.name)
def test_shell_script_shebang_is_clean(script: Path):
    first_line = script.read_bytes().split(b"\n", 1)[0]
    assert first_line.startswith(b"#!"), f"{script.name} has no shebang"
    assert not first_line.endswith(b"\r"), (
        f"{script.name} shebang ends with a carriage return, so the kernel will "
        f"look for an interpreter named {first_line[2:].decode(errors='replace')!r} "
        "and fail with a misleading 'No such file or directory'."
    )

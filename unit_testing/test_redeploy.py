"""deploy/redeploy.sh, run under bash against stub git and docker commands.

The stubs log every call to calls.log, so each test asserts both the outcome
and what was (not) run. No real git, docker or network is touched.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "deploy" / "redeploy.sh"

HEALTHY = '{"ok":true,"version":"abc1234","retailers":[{"retailer":"pccg"},{"retailer":"umart"}]}'

GIT_STUB = """#!/usr/bin/env bash
echo "git $*" >> "$CALLS"
case "$1" in
  diff) exit "${FAKE_DIRTY:-0}" ;;
  rev-parse) echo abc1234 ;;
esac
exit 0
"""

DOCKER_STUB = """#!/usr/bin/env bash
echo "docker GIT_SHA=${GIT_SHA:-} $*" >> "$CALLS"
case "$*" in
  "ps -a --filter name=^trackaroo$ --filter label=com.docker.compose.project -q") echo "${FAKE_COMPOSE_ID-cid123}" ;;
  "ps -a --filter name=^trackaroo$ -q") echo "${FAKE_ANY_ID-cid123}" ;;
  "compose ps -q --status running trackaroo") echo "${FAKE_RUNNING-cid123}" ;;
  "compose ps -q trackaroo") echo cid123 ;;
  "inspect -f {{.State.Health.Status}} cid123") echo "${FAKE_HEALTH:-healthy}" ;;
  "compose exec -T trackaroo python backup_db.py") exit "${FAKE_BACKUP_EXIT:-0}" ;;
  "compose exec -T trackaroo python repair_listings.py") echo "Re-pointed 3 listing(s) (dry run)" ;;
  "compose exec -T trackaroo node -e"*)
    n=$(( $(cat "$CALLS.healthz" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$CALLS.healthz"
    if [ -n "${FAKE_HEALTHZ_FIRST:-}" ] && [ "$n" -eq 1 ]; then printf '%s\\n' "$FAKE_HEALTHZ_FIRST"; else printf '%s\\n' "$FAKE_HEALTHZ"; fi ;;
esac
exit 0
"""


def _bash() -> str | None:
    """Git's bash on Windows (System32\\bash.exe is WSL, which cannot see
    Windows paths the same way); plain `bash` elsewhere."""
    if sys.platform == "win32":
        git = shutil.which("git")
        if not git:
            return None
        # git may resolve to Git/cmd/git.exe or Git/mingw64/bin/git.exe
        # depending on the calling shell's PATH; bash lives in Git/bin.
        for parent in Path(git).resolve().parents:
            candidate = parent / "bin" / "bash.exe"
            if candidate.exists():
                return str(candidate)
        return None
    return shutil.which("bash")


BASH = _bash()

# Put the stubs first from *inside* bash: Git for Windows' bin/bash.exe
# prepends its own /mingw64/bin and /usr/bin to the inherited PATH, which
# would put the real git ahead of the stub.
PREPEND_STUBS = (
    'stubs=$(cygpath -u "$STUBS" 2>/dev/null || printf %s "$STUBS"); '
    'PATH="$stubs:$PATH" exec bash "$0"'
)
pytestmark = pytest.mark.skipif(BASH is None, reason="bash not available")


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "deploy").mkdir()
    shutil.copy(SCRIPT, tmp_path / "deploy" / "redeploy.sh")
    (tmp_path / ".env").write_text("", encoding="utf-8")
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name, body in (("git", GIT_STUB), ("docker", DOCKER_STUB)):
        path = stubs / name
        path.write_bytes(body.encode())  # LF only
        path.chmod(0o755)
    return tmp_path


def run(project: Path, stdin: str = "", **env: str) -> tuple[subprocess.CompletedProcess, list[str]]:
    calls = project / "calls.log"
    full_env = {
        **os.environ,
        "STUBS": str(project / "stubs"),
        "CALLS": str(calls),
        "REDEPLOY_HOUR": "14",
        "POLL_SECONDS": "0",
        "FAKE_HEALTHZ": HEALTHY,
        **env,
    }
    result = subprocess.run(
        [BASH, "-c", PREPEND_STUBS, str(project / "deploy" / "redeploy.sh")],
        input=stdin, capture_output=True, text=True, env=full_env, cwd=project,
    )
    lines = calls.read_text().splitlines() if calls.exists() else []
    return result, lines


def _index(lines: list[str], needle: str) -> int:
    return next(i for i, line in enumerate(lines) if needle in line)


def test_happy_path_runs_every_step_in_order(project):
    result, calls = run(project, stdin="n\n")
    assert result.returncode == 0, result.stderr
    order = [
        "git pull --ff-only",
        "compose exec -T trackaroo python backup_db.py",
        "docker GIT_SHA=abc1234 compose build",
        "compose up -d",
        "inspect -f {{.State.Health.Status}} cid123",
        "compose exec -T trackaroo python repair_listings.py",
        "compose exec -T trackaroo node -e",
    ]
    positions = [_index(calls, step) for step in order]
    assert positions == sorted(positions)
    assert "abc1234" in result.stdout


def test_applies_repair_only_on_yes(project):
    _, calls = run(project, stdin="y\n")
    assert any("repair_listings.py --apply" in c for c in calls)


def test_never_applies_repair_without_a_yes(project):
    result, calls = run(project, stdin="")  # EOF: cron / piped ssh
    assert result.returncode == 0, result.stderr
    assert not any("--apply" in c for c in calls)
    assert "repair_listings.py --apply" in result.stdout  # tells the operator how


def test_refuses_a_dirty_checkout(project):
    result, calls = run(project, FAKE_DIRTY="1")
    assert result.returncode != 0
    assert not any("pull" in c or "compose build" in c for c in calls)


def test_refuses_inside_the_scrape_window(project):
    result, calls = run(project, REDEPLOY_HOUR="06")
    assert result.returncode != 0
    assert "FORCE=1" in result.stderr
    assert not any("compose build" in c for c in calls)


def test_force_allows_the_scrape_window(project):
    result, _ = run(project, stdin="n\n", REDEPLOY_HOUR="06", FORCE="1")
    assert result.returncode == 0, result.stderr


def test_refuses_when_a_non_compose_trackaroo_exists(project):
    result, calls = run(project, FAKE_COMPOSE_ID="", FAKE_ANY_ID="old999")
    assert result.returncode != 0
    assert "docker rename trackaroo trackaroo-old" in result.stderr
    assert not any("compose build" in c for c in calls)


def test_a_failed_backup_stops_before_the_build(project):
    result, calls = run(project, FAKE_BACKUP_EXIT="1")
    assert result.returncode != 0
    assert not any("compose build" in c for c in calls)


def test_no_running_container_needs_skip_backup(project):
    result, calls = run(project, FAKE_RUNNING="", FAKE_COMPOSE_ID="", FAKE_ANY_ID="")
    assert result.returncode != 0
    assert "SKIP_BACKUP=1" in result.stderr
    assert not any("compose build" in c for c in calls)
    result, _ = run(project, stdin="n\n", FAKE_RUNNING="", FAKE_COMPOSE_ID="", FAKE_ANY_ID="", SKIP_BACKUP="1")
    assert result.returncode == 0, result.stderr


def test_fails_when_the_container_never_turns_healthy(project):
    result, _ = run(project, FAKE_HEALTH="starting", HEALTH_TIMEOUT="0")
    assert result.returncode != 0
    assert "healthy" in result.stderr


def test_fails_when_healthz_reports_another_version(project):
    result, _ = run(project, stdin="n\n", FAKE_HEALTHZ=HEALTHY.replace("abc1234", "0ld5ha1"))
    assert result.returncode != 0
    assert "abc1234" in result.stderr


def test_fails_when_umart_is_missing(project):
    no_umart = '{"ok":true,"version":"abc1234","retailers":[{"retailer":"pccg"}]}'
    result, _ = run(project, stdin="n\n", FAKE_HEALTHZ=no_umart, VERIFY_TIMEOUT="0")
    assert result.returncode != 0
    assert "umart" in result.stderr


def test_waits_for_umart_to_appear(project):
    no_umart = '{"ok":true,"version":"abc1234","retailers":[{"retailer":"pccg"}]}'
    result, calls = run(project, stdin="n\n", FAKE_HEALTHZ_FIRST=no_umart)
    assert result.returncode == 0, result.stderr
    assert sum("compose exec -T trackaroo node -e" in c for c in calls) == 2


def test_every_exec_has_stdin_detached():
    # `docker compose exec -T` still forwards stdin: without </dev/null the
    # dry run would read the operator's "y" before the prompt does. The stubs
    # cannot show that, so pin it in the text.
    text = SCRIPT.read_text(encoding="utf-8")
    lines = text.splitlines()
    execs = [i for i, line in enumerate(lines) if "docker compose exec -T" in line]
    assert len(execs) == 4
    for i in execs:
        # A call continued with "\" carries the redirect on its next line.
        call = lines[i] + (lines[i + 1] if lines[i].endswith("\\") else "")
        assert "</dev/null" in call, lines[i]


def test_missing_env_file_stops_first(project):
    (project / ".env").unlink()
    result, calls = run(project)
    assert result.returncode != 0
    assert calls == []

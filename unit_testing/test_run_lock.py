"""Tests for run_lock: two run_daily processes must never overlap (#15)."""
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from run_lock import RunLockHeld, run_lock

ROOT = Path(__file__).resolve().parent.parent


def test_second_holder_is_refused_and_told_who_holds_it(tmp_path):
    lock = tmp_path / "run_daily.lock"
    with run_lock(lock):
        with pytest.raises(RunLockHeld) as held:
            with run_lock(lock):
                pass
    assert "pid" in str(held.value)


def test_lock_is_released_on_exit(tmp_path):
    lock = tmp_path / "run_daily.lock"
    with run_lock(lock):
        pass
    with run_lock(lock):
        pass


def test_lock_is_released_on_exception(tmp_path):
    lock = tmp_path / "run_daily.lock"
    with pytest.raises(ValueError):
        with run_lock(lock):
            raise ValueError("boom")
    with run_lock(lock):
        pass


def test_lock_is_released_when_the_holder_process_dies(tmp_path):
    # os._exit skips every finally block: only the OS can release the lock.
    lock = tmp_path / "run_daily.lock"
    code = textwrap.dedent(f"""
        import os, sys
        sys.path.insert(0, {str(ROOT)!r})
        from run_lock import run_lock
        cm = run_lock({str(lock)!r})
        cm.__enter__()
        os._exit(3)
    """)
    result = subprocess.run([sys.executable, "-c", code], timeout=60)
    assert result.returncode == 3
    with run_lock(lock):
        pass


def test_another_process_holding_the_lock_blocks_us(tmp_path):
    lock = tmp_path / "run_daily.lock"
    code = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(ROOT)!r})
        from run_lock import run_lock
        with run_lock({str(lock)!r}):
            print("held", flush=True)
            sys.stdin.readline()
    """)
    proc = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip() == "held"
        with pytest.raises(RunLockHeld):
            with run_lock(lock):
                pass
    finally:
        proc.stdin.write("\n")
        proc.stdin.flush()
        proc.wait(timeout=60)
    with run_lock(lock):
        pass


def test_main_exits_cleanly_without_running_when_the_lock_is_held(tmp_path, monkeypatch):
    import run_daily

    lock = tmp_path / "run_daily.lock"
    monkeypatch.setattr(run_daily, "RUN_LOCK_PATH", lock)
    ran = []
    monkeypatch.setattr(run_daily, "run", lambda args: ran.append(args) or 0)
    with run_lock(lock):
        run_daily.main(["--no-notify"])  # no SystemExit: an overlap is not a failure
    assert ran == []


def test_main_runs_and_releases_the_lock(tmp_path, monkeypatch):
    import run_daily

    lock = tmp_path / "run_daily.lock"
    monkeypatch.setattr(run_daily, "RUN_LOCK_PATH", lock)
    ran = []
    monkeypatch.setattr(run_daily, "run", lambda args: ran.append(args) or 0)
    run_daily.main(["--no-notify"])
    assert len(ran) == 1
    with run_lock(lock):
        pass


def test_lock_lives_next_to_the_database():
    # Read from source: conftest's autouse guard repoints the module attribute.
    src = (ROOT / "run_daily.py").read_text(encoding="utf-8")
    assert 'RUN_LOCK_PATH = DB_PATH.parent / "run_daily.lock"' in src

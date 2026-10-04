"""Exclusive lock so two run_daily.py processes never overlap (#15).

The scheduled run, a ``--pending-only`` boot catch-up and a manual
``docker compose exec`` run can all start at once. Overlapping runs scrape
twice (doubling PCCG's Algolia spend), race ``save_snapshot`` and ingest the
same files together. The lock is an OS file lock (``flock`` on Linux,
``msvcrt.locking`` on Windows), so the OS drops it when the holder exits, even
on a crash or SIGKILL: there is no stale-lock timeout to tune.

The file holds the holder's PID and start time, for the "already running"
log line. Its content is informational only; the lock is what counts.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator, Union

if os.name == "nt":
    import msvcrt

    # Lock one byte far past the PID line, so another process can still read
    # who holds it (Windows byte-range locks block reads of the locked range).
    _LOCK_OFFSET = 1 << 20

    def _try_lock(fd: int) -> None:
        os.lseek(fd, _LOCK_OFFSET, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)  # OSError when held elsewhere

    def _unlock(fd: int) -> None:
        os.lseek(fd, _LOCK_OFFSET, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _try_lock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # BlockingIOError when held

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


class RunLockHeld(Exception):
    """Another process holds the run lock. The message says who, if known."""


@contextmanager
def run_lock(path: Union[str, Path]) -> Iterator[None]:
    """Hold the run lock for the body of the ``with``, or raise RunLockHeld."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        try:
            _try_lock(fd)
        except OSError:
            raise RunLockHeld(_read_holder(fd)) from None
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            os.ftruncate(fd, 0)
            stamp = datetime.now().isoformat(timespec="seconds")
            os.write(fd, f"pid {os.getpid()} since {stamp}\n".encode())
            yield
        finally:
            _unlock(fd)
    finally:
        os.close(fd)


def _read_holder(fd: int) -> str:
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        text = os.read(fd, 200).decode(errors="replace").strip()
    except OSError:
        text = ""
    return text or "holder unknown"

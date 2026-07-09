from __future__ import annotations

import os

if os.name == "nt":
    import msvcrt
    import time

    def lock_exclusive(handle) -> None:
        handle.seek(0)
        while True:
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                time.sleep(0.05)

    def unlock(handle) -> None:
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass

else:
    import fcntl

    def lock_exclusive(handle) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)

    def unlock(handle) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

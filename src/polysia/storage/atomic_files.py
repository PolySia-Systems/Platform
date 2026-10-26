"""Bounded publication reads that permit atomic replacement on Windows."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def read_publication_bytes(path: Path, *, maximum_bytes: int) -> bytes:
    if path.is_symlink() or path.stat().st_size > maximum_bytes:
        raise ValueError("bounded_publication_file_required")
    if sys.platform == "win32":
        import ctypes
        import msvcrt
        from ctypes import wintypes

        create = ctypes.windll.kernel32.CreateFileW
        create.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        create.restype = wintypes.HANDLE
        # Python's normal file open omits FILE_SHARE_DELETE. An independent
        # reader must allow replacement while retaining its complete old view.
        handle = create(str(path.resolve()), 0x80000000, 7, None, 3, 0x80, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError()
        try:
            descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        except BaseException:
            ctypes.windll.kernel32.CloseHandle(wintypes.HANDLE(handle))
            raise
        with os.fdopen(descriptor, "rb") as stream:
            raw = stream.read(maximum_bytes + 1)
    else:
        with path.open("rb") as stream:
            raw = stream.read(maximum_bytes + 1)
    if len(raw) > maximum_bytes:
        raise ValueError("publication_file_exceeds_bound")
    return raw

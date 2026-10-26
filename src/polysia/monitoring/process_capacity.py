"""Process observations; absent host limits remain unknown denominators."""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path


class ProcessCapacity:
    def __init__(self) -> None:
        self._wall, self._cpu = time.monotonic(), time.process_time()

    def observation(self, root: Path) -> dict[str, object]:
        wall, cpu = time.monotonic(), time.process_time()
        elapsed = wall - self._wall
        percent = 100 * (cpu - self._cpu) / elapsed if elapsed > 0 else None
        self._wall, self._cpu = wall, cpu
        return {
            "process_cpu_percent_one_core": percent,
            "sample_seconds": elapsed,
            "peak_process_rss_bytes": peak_rss(),
            "disk_free_bytes": shutil.disk_usage(root).free,
            "host_logical_cpus": os.cpu_count(),
            "configured_cpu_limit": None,
            "configured_memory_limit_bytes": None,
            "host_network_limit": None,
        }


def peak_rss() -> int | None:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("page_faults", wintypes.DWORD)] + [
                (name, ctypes.c_size_t)
                for name in (
                    "peak_working_set",
                    "working_set",
                    "peak_paged",
                    "paged",
                    "peak_nonpaged",
                    "nonpaged",
                    "pagefile",
                    "peak_pagefile",
                )
            ]

        counter = Counters()
        counter.cb = ctypes.sizeof(counter)
        current = ctypes.windll.kernel32.GetCurrentProcess
        current.restype = wintypes.HANDLE
        observe = ctypes.windll.psapi.GetProcessMemoryInfo
        observe.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD]
        observe.restype = wintypes.BOOL
        if observe(current(), ctypes.byref(counter), counter.cb):
            return int(counter.peak_working_set)
        return None
    import resource

    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value) if sys.platform == "darwin" else int(value * 1024)

"""Ready-made preview frames (the idea behind StrokeScribe's preview cache).

Each frame is stored under a fingerprint of what is on screen at that moment:
the stickers showing, each one's settings and its own local frame number. So
editing one sticker only invalidates frames where that sticker appears, and
moving a sticker in time keeps its frames (they count from its own start).

Frames are kept in memory, least recently used dropped first, within a budget
that grows with the computer's memory.
"""
from __future__ import annotations

import hashlib
import json
import os
from collections import OrderedDict

from PySide6.QtGui import QImage


def physical_memory() -> int | None:
    try:
        if os.name == 'nt':
            import ctypes

            class Status(ctypes.Structure):
                _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong),
                            ('total', ctypes.c_ulonglong), ('free', ctypes.c_ulonglong),
                            ('page_total', ctypes.c_ulonglong), ('page_free', ctypes.c_ulonglong),
                            ('virtual_total', ctypes.c_ulonglong), ('virtual_free', ctypes.c_ulonglong),
                            ('extended', ctypes.c_ulonglong)]
            st = Status()
            st.length = ctypes.sizeof(Status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
                return int(st.total)
            return None
        return int(os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES'))
    except Exception:
        return None


def memory_budget() -> int:
    """A tenth of memory, between 400 MB and 3 GB."""
    total = physical_memory()
    if not total:
        return 400 * 1024 * 1024
    return int(max(400 * 1024 ** 2, min(3 * 1024 ** 3, total // 10)))


class FrameCache:
    def __init__(self, budget: int | None = None):
        self.budget = budget or memory_budget()
        self.frames: OrderedDict = OrderedDict()
        self.bytes = 0
        self._fps_rev = None
        self._fingerprints: dict[int, str] = {}

    # ---- fingerprints

    def refresh_fingerprints(self, timeline):
        """Call after the timeline changes (cheap: a few small JSON dumps)."""
        self._fingerprints = {
            c.id: hashlib.sha1(json.dumps({k: v for k, v in c.to_dict().items() if k != 'start'},
                                          sort_keys=True, default=str).encode()).hexdigest()[:16]
            for c in timeline.clips}

    def key(self, timeline, frame: int, width: int):
        t = frame / timeline.fps
        parts = []
        for c in timeline.active(t):
            fp = self._fingerprints.get(c.id)
            if fp is None:
                return None
            parts.append((c.track, fp, int(round((t - c.start) * timeline.fps))))
        return (width, timeline.width, timeline.height, timeline.fps, tuple(parts))

    # ---- storage

    def get(self, key) -> QImage | None:
        img = self.frames.get(key)
        if img is not None:
            self.frames.move_to_end(key)
        return img

    def put(self, key, img: QImage):
        if key is None or key in self.frames:
            return
        self.frames[key] = img
        self.bytes += img.sizeInBytes()
        while self.bytes > self.budget and len(self.frames) > 1:
            _, old = self.frames.popitem(last=False)
            self.bytes -= old.sizeInBytes()

    def has(self, key) -> bool:
        return key is not None and key in self.frames

    def clear(self):
        self.frames.clear()
        self.bytes = 0

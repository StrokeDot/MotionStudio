"""The open project: the timeline, what is selected, the playhead, and undo/redo."""
from __future__ import annotations

import json
import os

from PySide6.QtCore import QObject, Signal

from .effects import IN_OUT_BY_NAME, Phase
from .scene import ObjectSource
from .timeline import Clip, EffectInstance, Timeline, snapshot


class Document(QObject):
    changed = Signal()            # anything in the timeline changed
    selection_changed = Signal()
    time_changed = Signal()

    def __init__(self):
        super().__init__()
        self.timeline = Timeline()
        self.selected_id: int | None = None
        self.time = 0.0
        self.path = ''
        self._undo: list[dict] = []
        self._redo: list[dict] = []
        self.dirty = False

    # ---- selection / time

    def selected(self) -> Clip | None:
        return self.timeline.clip_by_id(self.selected_id) if self.selected_id is not None else None

    def select(self, clip: Clip | None):
        cid = clip.id if clip else None
        if cid != self.selected_id:
            self.selected_id = cid
            self.selection_changed.emit()

    def set_time(self, t: float):
        t = max(0.0, min(t, self.timeline.duration()))
        if abs(t - self.time) > 1e-9:
            self.time = t
            self.time_changed.emit()

    # ---- undo

    def checkpoint(self):
        """Call before a change so it can be undone."""
        self._undo.append(snapshot(self.timeline))
        if len(self._undo) > 200:
            self._undo.pop(0)
        self._redo.clear()
        self.dirty = True

    def _restore(self, data: dict):
        sel_index = None
        if self.selected():
            sel_index = self.timeline.clips.index(self.selected())
        self.timeline = Timeline.from_dict(data)
        clips = self.timeline.clips
        self.selected_id = clips[sel_index].id if sel_index is not None and sel_index < len(clips) else None
        self.changed.emit()
        self.selection_changed.emit()

    def undo(self):
        if self._undo:
            self._redo.append(snapshot(self.timeline))
            self._restore(self._undo.pop())

    def redo(self):
        if self._redo:
            self._undo.append(snapshot(self.timeline))
            self._restore(self._redo.pop())

    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    # ---- edits

    def add_sticker(self, source: ObjectSource, start: float | None = None, track: int | None = None,
                    duration: float = 4.0) -> Clip:
        self.checkpoint()
        tl = self.timeline
        start = self.time if start is None else max(0.0, start)
        clip = Clip(source=source, start=start, duration=duration)
        clip.track = tl.free_track_at(start, start + duration) if track is None else track
        tl.tracks = max(tl.tracks, clip.track + 1)
        clip.fit(tl.width, tl.height, 0.4 if source.kind != 'text' else 0.3)
        tl.clips.append(clip)
        self.selected_id = clip.id
        self.changed.emit()
        self.selection_changed.emit()
        return clip

    def set_transition(self, clip: Clip, effect: str, which: str = 'in', settings: dict | None = None):
        self.checkpoint()
        old = clip.trans_in if which == 'in' else clip.trans_out
        ph = Phase.from_dict(settings) if settings else Phase(effect=effect, direction=old.direction,
                                                                duration=min(1.2, max(0.3, clip.duration / 3)))
        ph.effect = effect
        if which == 'in':
            clip.trans_in = ph
        else:
            clip.trans_out = ph
        self.changed.emit()

    def add_effect(self, clip: Clip, type_id: str, params: dict | None = None):
        self.checkpoint()
        clip.effects.append(EffectInstance(type_id, True, dict(params or {})))
        self.changed.emit()

    def delete_selected(self):
        clip = self.selected()
        if clip:
            self.checkpoint()
            self.timeline.clips.remove(clip)
            self.selected_id = None
            self.changed.emit()
            self.selection_changed.emit()

    def duplicate_selected(self):
        clip = self.selected()
        if clip:
            self.checkpoint()
            c = clip.clone()
            c.start = clip.end
            c.track = clip.track
            if any(o.track == c.track and o.start < c.end and o.end > c.start for o in self.timeline.clips):
                c.track = self.timeline.free_track_at(c.start, c.end)
            self.timeline.clips.append(c)
            self.selected_id = c.id
            self.changed.emit()
            self.selection_changed.emit()

    def split_selected(self):
        clip = self.selected()
        t = self.time
        if not clip or not (clip.start + 0.05 < t < clip.end - 0.05):
            return False
        self.checkpoint()
        right = clip.clone()
        right.start = t
        right.duration = clip.end - t
        clip.duration = t - clip.start
        clip.trans_out = Phase(effect='None', direction=clip.trans_out.direction)
        right.trans_in = Phase(effect='None', direction=right.trans_in.direction)
        self.timeline.clips.append(right)
        self.changed.emit()
        return True

    def add_track(self):
        self.checkpoint()
        self.timeline.tracks += 1
        self.changed.emit()

    def notify(self):
        """Something was edited in place (after checkpoint())."""
        self.dirty = True
        self.changed.emit()

    # ---- files

    def new(self):
        self.timeline = Timeline()
        self.selected_id = None
        self.time = 0.0
        self.path = ''
        self._undo.clear()
        self._redo.clear()
        self.dirty = False
        self.changed.emit()
        self.selection_changed.emit()
        self.time_changed.emit()

    def save(self, path: str):
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'app': 'Motion Studio', 'version': 2, 'timeline': self.timeline.to_dict()}, f, indent=2)
        os.replace(tmp, path)
        self.path = path
        self.dirty = False

    def open(self, path: str):
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        tl = Timeline.from_dict(data.get('timeline') or {})
        self.timeline = tl
        self.path = path
        self.selected_id = None
        self.time = 0.0
        self._undo.clear()
        self._redo.clear()
        self.dirty = False
        self.changed.emit()
        self.selection_changed.emit()
        self.time_changed.emit()


def transition_names() -> list[str]:
    return [n for n in IN_OUT_BY_NAME if n != 'None']

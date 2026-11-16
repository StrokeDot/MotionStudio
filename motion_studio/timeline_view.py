"""Bottom timeline: tracks, sticker clips (drag to move, drag edges to trim),
transition and effect markers, the playhead, and drops from the library."""
from __future__ import annotations

import json
import math

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QHBoxLayout, QMenu, QScrollBar, QSlider, QToolButton, QVBoxLayout, QWidget

from .document import Document
from .library import MIME, sticker_source
from .theme import ACCENT, BG, CLIP_COLORS, LINE, MUTED, PANEL, PLAYHEAD, TEXT, icon

HEADER_W = 128
RULER_H = 30
ROW_H = 64
EDGE = 7


class TimelineCanvas(QWidget):
    message = Signal(str)

    def __init__(self, doc: Document):
        super().__init__()
        self.doc = doc
        self.pps = 90.0                 # pixels per second
        self.xoff = 0.0
        self.yoff = 0.0
        self.locked: set[int] = set()
        self._drag = None
        self._drop = None               # (kind, info) while dragging from the library
        self._thumbs: dict = {}
        self._snap_line = None
        self._hover_id = None
        self._autoscroll = QTimer(self)
        self._autoscroll.timeout.connect(self._autoscroll_step)
        self._last_pos = None
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(RULER_H + ROW_H * 2)
        doc.changed.connect(self.update)
        doc.time_changed.connect(self._follow)
        doc.selection_changed.connect(self.update)

    # ---- geometry

    def x_of(self, t: float) -> float:
        return HEADER_W + t * self.pps - self.xoff

    def t_of(self, x: float) -> float:
        return max(0.0, (x - HEADER_W + self.xoff) / self.pps)

    def row_y(self, track: int) -> float:
        return RULER_H + (self.doc.timeline.tracks - 1 - track) * ROW_H - self.yoff

    def track_at(self, y: float) -> int | None:
        if y < RULER_H:
            return None
        i = int((y - RULER_H + self.yoff) // ROW_H)
        tr = self.doc.timeline.tracks - 1 - i
        return tr if 0 <= tr < self.doc.timeline.tracks else None

    def clip_rect(self, clip) -> QRectF:
        x0, x1 = self.x_of(clip.start), self.x_of(clip.end)
        y = self.row_y(clip.track)
        return QRectF(x0, y + 4, max(4.0, x1 - x0), ROW_H - 8)

    def clip_at(self, pos):
        for clip in sorted(self.doc.timeline.clips, key=lambda c: c.id == self.doc.selected_id, reverse=True):
            if self.clip_rect(clip).contains(pos) and pos.x() > HEADER_W:
                return clip
        return None

    def content_width(self) -> float:
        return (self.doc.timeline.duration() + 10) * self.pps

    def content_height(self) -> float:
        return self.doc.timeline.tracks * ROW_H

    # ---- painting

    def _tick_step(self):
        for step in (0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300):
            if step * self.pps >= 70:
                return step
        return 600

    def _thumb(self, clip, h: int) -> QImage:
        key = (json.dumps(clip.source.to_dict(), sort_keys=True), h)
        img = self._thumbs.get(key)
        if img is None:
            try:
                nw, nh = clip.source.native_size()
                src = clip.source.image_at(0.0, h / max(1.0, nh))
                img = src.scaled(QSize(int(h * nw / max(1.0, nh)) or 1, h), Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
            except Exception:
                img = QImage()
            if len(self._thumbs) > 200:
                self._thumbs.clear()
            self._thumbs[key] = img
        return img

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        tl = self.doc.timeline
        W, H = self.width(), self.height()
        p.fillRect(0, 0, W, H, QColor(BG))

        # Track rows
        for tr in range(tl.tracks):
            y = self.row_y(tr)
            if y + ROW_H < RULER_H or y > H:
                continue
            p.fillRect(QRectF(HEADER_W, y, W - HEADER_W, ROW_H), QColor('#17181c' if tr % 2 else '#1a1b20'))
            p.setPen(QColor(LINE))
            p.drawLine(QPointF(HEADER_W, y + ROW_H), QPointF(W, y + ROW_H))

        # Clips
        p.save()
        p.setClipRect(QRectF(HEADER_W, RULER_H, W - HEADER_W, H - RULER_H))
        for clip in tl.clips:
            self._paint_clip(p, clip)
        if self._drop and self._drop[0] == 'ghost':
            _, t, tr, dur = self._drop
            r = QRectF(self.x_of(t), self.row_y(tr) + 4, dur * self.pps, ROW_H - 8)
            p.setPen(QPen(QColor(ACCENT), 2, Qt.PenStyle.DashLine))
            p.setBrush(QColor(33, 212, 177, 40))
            p.drawRoundedRect(r, 6, 6)
        p.restore()

        # Headers
        p.fillRect(QRectF(0, RULER_H, HEADER_W, H - RULER_H), QColor(PANEL))
        for tr in range(tl.tracks):
            y = self.row_y(tr)
            if y + ROW_H < RULER_H or y > H:
                continue
            p.save()
            p.setClipRect(QRectF(0, RULER_H, HEADER_W, H - RULER_H))
            p.setPen(QColor('#c9ccd2'))
            p.drawText(QRectF(12, y + 8, HEADER_W - 16, 20), Qt.AlignmentFlag.AlignLeft, f'Track {tr + 1}')
            hidden = tr in tl.hidden_tracks
            icon('eye_off' if hidden else 'eye', MUTED if hidden else TEXT, 18).paint(
                p, QRect(12, int(y) + 34, 18, 18))
            locked = tr in self.locked
            icon('lock' if locked else 'unlock', TEXT if locked else MUTED, 18).paint(
                p, QRect(40, int(y) + 34, 18, 18))
            p.setPen(QColor(LINE))
            p.drawLine(QPointF(0, y + ROW_H), QPointF(HEADER_W, y + ROW_H))
            p.restore()
        p.setPen(QColor(LINE))
        p.drawLine(QPointF(HEADER_W, RULER_H), QPointF(HEADER_W, H))

        # Ruler
        p.fillRect(QRectF(0, 0, W, RULER_H), QColor(BG))
        step = self._tick_step()
        t0 = self.t_of(HEADER_W)
        t1 = self.t_of(W)
        k = math.floor(t0 / step)
        f = p.font()
        f.setPixelSize(11)
        p.setFont(f)
        while k * step <= t1 + step:
            t = k * step
            x = self.x_of(t)
            if x >= HEADER_W:
                p.setPen(QColor('#6b707a'))
                p.drawLine(QPointF(x, RULER_H - 10), QPointF(x, RULER_H))
                for sub in range(1, 5):
                    xs = self.x_of(t + step * sub / 5)
                    p.drawLine(QPointF(xs, RULER_H - 5), QPointF(xs, RULER_H))
                p.setPen(QColor('#a3a8b1'))
                p.drawText(QPointF(x + 3, 13), self._fmt(t, step))
            k += 1
        p.setPen(QColor(LINE))
        p.drawLine(QPointF(0, RULER_H), QPointF(W, RULER_H))
        dur_x = self.x_of(tl.duration())
        p.setPen(QPen(QColor(PLAYHEAD), 2))
        p.drawLine(QPointF(HEADER_W, RULER_H - 1), QPointF(max(HEADER_W, dur_x), RULER_H - 1))
        # Frames already prepared for smooth playback.
        p.setPen(QPen(QColor(ACCENT), 2))
        for a, b in getattr(self.doc, 'ready_ranges', []):
            xa, xb = max(HEADER_W, self.x_of(a)), self.x_of(b)
            if xb > xa:
                p.drawLine(QPointF(xa, RULER_H - 1), QPointF(xb, RULER_H - 1))
        if self._snap_line is not None:
            xs = self.x_of(self._snap_line)
            p.setPen(QPen(QColor('#ffd23f'), 1, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(xs, RULER_H), QPointF(xs, H))

        # Playhead
        x = self.x_of(self.doc.time)
        if x >= HEADER_W - 1:
            p.setPen(QPen(QColor(PLAYHEAD), 2))
            p.drawLine(QPointF(x, 4), QPointF(x, H))
            p.setBrush(QColor(PLAYHEAD))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(x - 6, 2, 12, 14), 4, 4)

    def _fmt(self, t, step):
        m, s = divmod(t, 60)
        if step < 1:
            return f'{int(m):02d}:{s:05.2f}'
        return f'{int(m):02d}:{int(round(s)):02d}'

    def _paint_clip(self, p: QPainter, clip):
        r = self.clip_rect(clip)
        if r.right() < HEADER_W or r.left() > self.width():
            return
        selected = clip.id == self.doc.selected_id
        base = QColor(CLIP_COLORS.get(clip.source.kind, '#1f6e5c'))
        if clip.track in self.doc.timeline.hidden_tracks:
            base = base.darker(170)
        path = QPainterPath()
        path.addRoundedRect(r, 6, 6)
        p.fillPath(path, base.darker(140))
        head = QRectF(r.left(), r.top(), r.width(), 20)
        p.save()
        p.setClipPath(path)
        p.fillRect(head, base)
        # film strip of the sticker
        th = int(r.height() - 26)
        img = self._thumb(clip, th) if th > 8 else QImage()
        if not img.isNull():
            stepx = max(img.width() + 14, 70)
            x = r.left() + 8
            while x < r.right():
                p.drawImage(QPointF(x, r.top() + 23), img)
                x += stepx
        # transitions
        for which, ph in (('in', clip.trans_in), ('out', clip.trans_out)):
            if ph.effect == 'None':
                continue
            w = min(r.width() / 2, ph.duration * self.pps)
            g = QLinearGradient()
            if which == 'in':
                g.setStart(r.left(), 0)
                g.setFinalStop(r.left() + w, 0)
                box = QRectF(r.left(), r.top(), w, r.height())
            else:
                g.setStart(r.right(), 0)
                g.setFinalStop(r.right() - w, 0)
                box = QRectF(r.right() - w, r.top(), w, r.height())
            g.setColorAt(0, QColor(255, 255, 255, 90))
            g.setColorAt(1, QColor(255, 255, 255, 0))
            p.fillRect(box, g)
            p.setPen(QColor('#ffffff'))
            f = p.font()
            f.setPixelSize(10)
            p.setFont(f)
            lab = ('▶ ' if which == 'in' else '') + ph.effect + (' ◀' if which == 'out' else '')
            al = Qt.AlignmentFlag.AlignLeft if which == 'in' else Qt.AlignmentFlag.AlignRight
            p.drawText(QRectF(box.left() + 4, r.bottom() - 16, box.width() - 8, 14), al | Qt.AlignmentFlag.AlignVCenter, lab)
        p.restore()
        # name + badges
        p.setPen(QColor('#ffffff'))
        f = p.font()
        f.setPixelSize(12)
        p.setFont(f)
        fx = len([e for e in clip.effects if e.enabled])
        badge = f'  fx {fx}' if fx else ''
        p.drawText(QRectF(r.left() + 8, r.top() + 2, r.width() - 12, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, clip.name() + badge)
        if not selected and clip.id == self._hover_id:
            p.setPen(QPen(QColor(255, 255, 255, 110), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 6, 6)
        if selected:
            p.setPen(QPen(QColor('#ffffff'), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 6, 6)
        if self._drop and self._drop[0] == 'target' and self._drop[1] == clip.id:
            which = self._drop[2]
            half = QRectF(r.left(), r.top(), r.width() / 2, r.height()) if which in ('in', 'all') else \
                QRectF(r.center().x(), r.top(), r.width() / 2, r.height())
            if which == 'all':
                half = r
            p.setPen(QPen(QColor(ACCENT), 2))
            p.setBrush(QColor(33, 212, 177, 60))
            p.drawRoundedRect(half, 6, 6)

    # ---- scrolling

    def _follow(self):
        x = self.x_of(self.doc.time)
        if x > self.width() - 40:
            self.xoff += x - (self.width() - 120)
            self.parent_scroll_sync()
        elif x < HEADER_W:
            self.xoff = max(0.0, self.xoff - (HEADER_W - x) - 40)
            self.parent_scroll_sync()
        self.update()

    def parent_scroll_sync(self):
        panel = self.parent()
        if hasattr(panel, 'sync_scrollbars'):
            panel.sync_scrollbars()

    def set_zoom(self, pps: float, anchor_x: float | None = None):
        anchor_x = self.x_of(self.doc.time) if anchor_x is None else anchor_x
        t = self.t_of(anchor_x)
        self.pps = max(8.0, min(600.0, pps))
        self.xoff = max(0.0, t * self.pps - (anchor_x - HEADER_W))
        self.parent_scroll_sync()
        self.update()

    def wheelEvent(self, e):
        d = e.angleDelta().y() or e.angleDelta().x()
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.set_zoom(self.pps * (1.15 if d > 0 else 1 / 1.15), e.position().x())
        elif e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.yoff = max(0.0, min(max(0.0, self.content_height() - (self.height() - RULER_H)),
                                     self.yoff - d / 2))
            self.parent_scroll_sync()
        else:
            self.xoff = max(0.0, self.xoff - d)
            self.parent_scroll_sync()
        self.update()

    # ---- mouse

    def _header_click(self, pos):
        tr = self.track_at(pos.y())
        if tr is None:
            return
        y = self.row_y(tr)
        tl = self.doc.timeline
        if QRectF(8, y + 30, 26, 26).contains(pos):
            self.doc.checkpoint()
            tl.hidden_tracks ^= {tr}
            self.doc.notify()
        elif QRectF(36, y + 30, 26, 26).contains(pos):
            self.locked ^= {tr}
            self.update()

    def mousePressEvent(self, e):
        pos = e.position()
        self.setFocus()
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if pos.x() < HEADER_W:
            self._header_click(pos)
            return
        if pos.y() < RULER_H or abs(pos.x() - self.x_of(self.doc.time)) < 5 and pos.y() < RULER_H + 6:
            self._drag = {'mode': 'scrub'}
            self.doc.set_time(self.t_of(pos.x()))
            return
        clip = self.clip_at(pos)
        if clip is None:
            self.doc.select(None)
            self._drag = {'mode': 'scrub'}
            self.doc.set_time(self.t_of(pos.x()))
            return
        self.doc.select(clip)
        if clip.track in self.locked:
            self.message.emit('That track is locked.')
            return
        r = self.clip_rect(clip)
        mode = 'move'
        if pos.x() - r.left() < EDGE:
            mode = 'trim_l'
        elif r.right() - pos.x() < EDGE:
            mode = 'trim_r'
        self._drag = {'mode': mode, 'clip': clip, 'x': pos.x(), 'start': clip.start, 'dur': clip.duration,
                      'track': clip.track, 'moved': False, 'xoff': self.xoff}

    def _snap(self, t: float, exclude) -> float:
        cands = [0.0, self.doc.time]
        for c in self.doc.timeline.clips:
            if c is not exclude:
                cands += [c.start, c.end]
        best = min(cands, key=lambda c: abs(c - t))
        if abs(best - t) * self.pps < 8:
            self._snap_line = best
            return best
        return t

    def _overlaps(self, clip, start, dur, track):
        return any(o is not clip and o.track == track and o.start < start + dur - 1e-6 and o.end > start + 1e-6
                   for o in self.doc.timeline.clips)

    def mouseMoveEvent(self, e):
        pos = e.position()
        d = self._drag
        if not d:
            clip = self.clip_at(pos)
            if clip:
                r = self.clip_rect(clip)
                edge = pos.x() - r.left() < EDGE or r.right() - pos.x() < EDGE
                self.setCursor(Qt.CursorShape.SizeHorCursor if edge else Qt.CursorShape.OpenHandCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            hid = clip.id if clip else None
            if hid != self._hover_id:
                self._hover_id = hid
                self.update()
            return
        if d['mode'] == 'scrub':
            self.doc.set_time(self.t_of(pos.x()))
            return
        clip = d['clip']
        self._last_pos = pos
        if not self._autoscroll.isActive():
            self._autoscroll.start(30)
        self._snap_line = None
        dt = (pos.x() - d['x'] + self.xoff - d.get('xoff', self.xoff)) / self.pps
        if not d['moved'] and abs(pos.x() - d['x']) < 3:
            return
        if not d['moved']:
            self.doc.checkpoint()
            d['moved'] = True
        if d['mode'] == 'move':
            start = max(0.0, d['start'] + dt)
            s1 = self._snap(start, clip)
            s2 = self._snap(start + clip.duration, clip) - clip.duration
            start = s1 if abs(s1 - start) <= abs(s2 - start) else max(0.0, s2)
            tr = self.track_at(pos.y())
            tr = d['track'] if tr is None or tr in self.locked else tr
            if not self._overlaps(clip, start, clip.duration, tr):
                clip.start, clip.track = start, tr
            elif not self._overlaps(clip, start, clip.duration, clip.track):
                clip.start = start
        elif d['mode'] == 'trim_l':
            end = d['start'] + d['dur']
            start = min(end - 0.1, max(0.0, self._snap(d['start'] + dt, clip)))
            if not self._overlaps(clip, start, end - start, clip.track):
                clip.start, clip.duration = start, end - start
        else:
            end = max(clip.start + 0.1, self._snap(d['start'] + d['dur'] + dt, clip))
            if not self._overlaps(clip, clip.start, end - clip.start, clip.track):
                clip.duration = end - clip.start
        self.doc.notify()

    def mouseReleaseEvent(self, _):
        self._drag = None
        self._snap_line = None
        self._autoscroll.stop()
        self.update()

    def _autoscroll_step(self):
        """While dragging a clip near the left/right edge, scroll the timeline."""
        d, pos = self._drag, self._last_pos
        if not d or pos is None or d['mode'] == 'scrub':
            self._autoscroll.stop()
            return
        step = 0.0
        if pos.x() > self.width() - 40:
            step = (pos.x() - (self.width() - 40)) * 0.6
        elif pos.x() < HEADER_W + 30 and self.xoff > 0:
            step = -(HEADER_W + 30 - pos.x()) * 0.6
        if step:
            self.xoff = max(0.0, self.xoff + step)
            self.parent_scroll_sync()
            from PySide6.QtGui import QMouseEvent
            from PySide6.QtCore import QEvent
            ev = QMouseEvent(QEvent.Type.MouseMove, pos, pos, Qt.MouseButton.NoButton,
                             Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            self.mouseMoveEvent(ev)

    def contextMenuEvent(self, e):
        pos = e.pos()
        clip = self.clip_at(QPointF(pos))
        m = QMenu(self)
        if clip:
            self.doc.select(clip)
            m.addAction('Duplicate', self.doc.duplicate_selected)
            m.addAction('Split at playhead', lambda: self.doc.split_selected() or
                        self.message.emit('Put the playhead inside the sticker to split it.'))
            m.addSeparator()
            for which, ph in (('in', clip.trans_in), ('out', clip.trans_out)):
                if ph.effect != 'None':
                    m.addAction(f'Remove {"In" if which == "in" else "Out"} transition ({ph.effect})',
                                lambda w=which: self.doc.set_transition(clip, 'None', w))
            if clip.effects:
                def clear_fx():
                    self.doc.checkpoint()
                    clip.effects.clear()
                    self.doc.notify()
                m.addAction(f'Remove all effects ({len(clip.effects)})', clear_fx)
            m.addSeparator()
            m.addAction('Delete', self.doc.delete_selected)
        else:
            m.addAction('Add track', self.doc.add_track)
            m.addAction('Zoom to fit', self.zoom_to_fit)
        m.exec(e.globalPos())

    def zoom_to_fit(self):
        dur = max(1.0, self.doc.timeline.duration())
        self.pps = max(8.0, min(600.0, (self.width() - HEADER_W - 40) / dur))
        self.xoff = 0.0
        self.parent_scroll_sync()
        self.update()

    def mouseDoubleClickEvent(self, e):
        clip = self.clip_at(e.position())
        if clip:
            self.doc.set_time(max(clip.start, min(clip.end - 1e-3, self.t_of(e.position().x()))))

    # ---- drops from the library

    def _drop_info(self, e):
        try:
            item = json.loads(bytes(e.mimeData().data(MIME)).decode())
        except Exception:
            return None, None
        return item, e.position()

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        item, pos = self._drop_info(e)
        if not item:
            return
        if item['kind'] == 'sticker':
            tr = self.track_at(pos.y())
            tr = 0 if tr is None else tr
            self._drop = ('ghost', self.t_of(pos.x()), tr, 4.0)
        else:
            clip = self.clip_at(pos)
            if clip:
                r = self.clip_rect(clip)
                which = 'all' if item['kind'] == 'effect' else ('in' if pos.x() < r.center().x() else 'out')
                self._drop = ('target', clip.id, which)
            else:
                self._drop = None
        e.acceptProposedAction()
        self.update()

    def dragLeaveEvent(self, _):
        self._drop = None
        self.update()

    def dropEvent(self, e):
        item, pos = self._drop_info(e)
        self._drop = None
        self.update()
        if not item:
            return
        if item['kind'] == 'sticker':
            tr = self.track_at(pos.y())
            start = self.t_of(pos.x())
            tl = self.doc.timeline
            if tr is None or self._overlaps(None, start, 4.0, tr):
                tr = None
            try:
                self.doc.add_sticker(sticker_source(item), start=start, track=tr)
            except Exception as exc:
                self.message.emit(f'Could not add that sticker: {exc}')
            return
        clip = self.clip_at(pos)
        if clip is None:
            self.message.emit('Drop it onto a sticker on the timeline.')
            return
        self.doc.select(clip)
        if item['kind'] == 'transition':
            which = 'in' if pos.x() < self.clip_rect(clip).center().x() else 'out'
            self.doc.set_transition(clip, item['effect'], which, item.get('settings'))
            self.message.emit(f'{item["name"]} added as the {"In" if which == "in" else "Out"} transition.')
        elif item['kind'] == 'effect':
            self.doc.add_effect(clip, item['type'], item.get('params'))
            self.message.emit(f'{item["name"]} added.')
        e.acceptProposedAction()


class TimelinePanel(QWidget):
    message = Signal(str)

    def __init__(self, doc: Document):
        super().__init__()
        self.doc = doc
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(2)
        bar = QHBoxLayout()
        self.buttons = {}
        for name, tip, fn in (('undo', 'Undo  (Ctrl+Z)', doc.undo), ('redo', 'Redo  (Ctrl+Y)', doc.redo),
                              ('delete', 'Delete  (Del)', doc.delete_selected),
                              ('split', 'Split at playhead  (Ctrl+B)', self._split),
                              ('track_add', 'Add a track', doc.add_track)):
            b = QToolButton()
            b.setIcon(icon(name))
            b.setIconSize(QSize(20, 20))
            b.setToolTip(tip)
            b.clicked.connect(fn)
            bar.addWidget(b)
            self.buttons[name] = b
        bar.addStretch(1)
        fit = QToolButton()
        fit.setText('Fit')
        fit.setToolTip('Zoom to fit the whole video')
        fit.clicked.connect(lambda: self.canvas.zoom_to_fit())
        bar.addWidget(fit)
        zo = QToolButton()
        zo.setIcon(icon('zoom_out'))
        zo.setToolTip('Zoom out  (Ctrl+wheel)')
        zi = QToolButton()
        zi.setIcon(icon('zoom_in'))
        zi.setToolTip('Zoom in  (Ctrl+wheel)')
        self.zoom = QSlider(Qt.Orientation.Horizontal)
        self.zoom.setRange(0, 100)
        self.zoom.setFixedWidth(140)
        bar.addWidget(zo)
        bar.addWidget(self.zoom)
        bar.addWidget(zi)
        lay.addLayout(bar)

        body = QHBoxLayout()
        body.setSpacing(0)
        col = QVBoxLayout()
        col.setSpacing(0)
        self.canvas = TimelineCanvas(doc)
        self.canvas.setParent(self)
        self.canvas.message.connect(self.message)
        col.addWidget(self.canvas, 1)
        self.hbar = QScrollBar(Qt.Orientation.Horizontal)
        col.addWidget(self.hbar)
        body.addLayout(col, 1)
        self.vbar = QScrollBar(Qt.Orientation.Vertical)
        body.addWidget(self.vbar)
        lay.addLayout(body, 1)

        self.hbar.valueChanged.connect(self._hscroll)
        self.vbar.valueChanged.connect(self._vscroll)
        self.zoom.valueChanged.connect(self._zoom_slider)
        zo.clicked.connect(lambda: self.canvas.set_zoom(self.canvas.pps / 1.4))
        zi.clicked.connect(lambda: self.canvas.set_zoom(self.canvas.pps * 1.4))
        doc.changed.connect(self.sync_scrollbars)
        doc.changed.connect(self._update_buttons)
        doc.selection_changed.connect(self._update_buttons)
        self.sync_scrollbars()
        self._update_buttons()

    def _split(self):
        if not self.doc.split_selected():
            self.message.emit('Select a sticker and put the playhead inside it to split.')

    def _update_buttons(self):
        self.buttons['undo'].setEnabled(self.doc.can_undo())
        self.buttons['redo'].setEnabled(self.doc.can_redo())
        self.buttons['delete'].setEnabled(self.doc.selected() is not None)
        self.buttons['split'].setEnabled(self.doc.selected() is not None)

    def _zoom_slider(self, v):
        pps = 8 * (600 / 8) ** (v / 100)
        if abs(pps - self.canvas.pps) > 0.5:
            self.canvas.set_zoom(pps)

    def sync_scrollbars(self):
        c = self.canvas
        for bar, val, rng, page in ((self.hbar, c.xoff, max(0, c.content_width() - (c.width() - HEADER_W)),
                                     c.width() - HEADER_W),
                                    (self.vbar, c.yoff, max(0, c.content_height() - (c.height() - RULER_H)),
                                     c.height() - RULER_H)):
            bar.blockSignals(True)
            bar.setRange(0, int(rng))
            bar.setPageStep(max(1, int(page)))
            bar.setValue(int(val))
            bar.blockSignals(False)
        self.vbar.setVisible(self.vbar.maximum() > 0)
        self.zoom.blockSignals(True)
        self.zoom.setValue(int(round(100 * math.log(c.pps / 8) / math.log(600 / 8))))
        self.zoom.blockSignals(False)

    def _hscroll(self, v):
        self.canvas.xoff = float(v)
        self.canvas.update()

    def _vscroll(self, v):
        self.canvas.yoff = float(v)
        self.canvas.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.sync_scrollbars()

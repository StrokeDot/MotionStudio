"""Top-centre player: preview, scrubber, timecode and transport buttons.

Smoothness (as in StrokeScribe): frames are cached once made, the player
quietly pre-renders the frames ahead of the playhead whenever it is idle, and
playback follows an exact clock, showing the frame for the current moment.
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QTransform
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel, QSlider, QToolButton,
                               QVBoxLayout, QWidget)

from .document import Document
from .preview_cache import FrameCache
from .theme import ACCENT, BG, TEXT, icon
from .timeline import clip_bounds, clip_box, render_timeline

ASPECTS = [('1440p 16:9', 2560, 1440), ('1080p 16:9', 1920, 1080), ('9:16', 1080, 1920), ('1:1', 1080, 1080),
           ('4:5', 1080, 1350), ('4K 16:9', 3840, 2160)]
QUALITY = [('Full Quality', 1.0), ('1/2', 0.5), ('1/4', 0.25)]
HANDLE = 7          # handle half-size in screen pixels
SNAP_PX = 8


def timecode(t: float, fps: float) -> str:
    total_frames = int(round(t * fps))
    f = total_frames % int(round(fps))
    s = int(total_frames // fps)
    return f'{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}:{f:02d}'


class Canvas(QWidget):
    """The picture. Click a sticker to select it; drag to move, corners to resize,
    the round handle to rotate. Moving snaps to the centre lines (hold Alt to stop)."""

    def __init__(self, doc: Document, player: 'PlayerPanel'):
        super().__init__()
        self.doc = doc
        self.player = player
        self.frame: QImage | None = None
        self.background = 'checker'
        self.bg_image: QImage | None = None
        self._drag = None
        self._guides = (False, False)
        self.setMinimumSize(360, 200)
        self.setMouseTracking(True)

    # ---- geometry

    def canvas_rect(self) -> QRectF:
        tl = self.doc.timeline
        w, h = self.width() - 12, self.height() - 12
        k = min(w / tl.width, h / tl.height)
        cw, ch = tl.width * k, tl.height * k
        return QRectF((self.width() - cw) / 2, (self.height() - ch) / 2, cw, ch)

    def _k(self) -> float:
        return self.canvas_rect().width() / self.doc.timeline.width

    def _to_canvas(self, pos) -> QPointF:
        r = self.canvas_rect()
        k = self._k()
        return QPointF((pos.x() - r.left()) / k, (pos.y() - r.top()) / k)

    def _box(self):
        """Selected sticker's box in screen space: (transform, w, h) or None."""
        clip = self.doc.selected()
        tl = self.doc.timeline
        if not clip or not (clip.start <= self.doc.time < clip.end) or self.player.playing \
                or clip.track in tl.hidden_tracks:
            return None
        cx, cy, w, h, ang = clip_box(clip, self.doc.time - clip.start, tl.width, tl.height)
        r = self.canvas_rect()
        k = self._k()
        tr = QTransform()
        tr.translate(r.left() + cx * k, r.top() + cy * k)
        tr.rotate(ang)
        return tr, w * k, h * k

    def _handles(self):
        box = self._box()
        if not box:
            return {}
        tr, w, h = box
        pts = {'tl': (-w / 2, -h / 2), 'tr': (w / 2, -h / 2), 'br': (w / 2, h / 2), 'bl': (-w / 2, h / 2),
               'rot': (0, -h / 2 - 26)}
        return {n: tr.map(QPointF(*p)) for n, p in pts.items()}

    # ---- painting

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(BG))
        r = self.canvas_rect()
        if self.background == 'checker':
            s = 12
            p.save()
            p.setClipRect(r)
            p.fillRect(r, QColor('#e9e9e9'))
            for yi in range(int(r.height() / s) + 1):
                for xi in range(int(r.width() / s) + 1):
                    if (xi + yi) % 2:
                        p.fillRect(QRectF(r.left() + xi * s, r.top() + yi * s, s, s), QColor('#c4c4c4'))
            p.restore()
        elif self.background == 'image' and self.bg_image is not None:
            p.drawImage(r, self.bg_image)
        else:
            p.fillRect(r, QColor(self.background))
        if self.frame is not None:
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawImage(r, self.frame)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        gx, gy = self._guides
        if self._drag and (gx or gy):
            p.setPen(QPen(QColor('#ff4fd8'), 1, Qt.PenStyle.DashLine))
            if gx:
                p.drawLine(QPointF(r.center().x(), r.top()), QPointF(r.center().x(), r.bottom()))
            if gy:
                p.drawLine(QPointF(r.left(), r.center().y()), QPointF(r.right(), r.center().y()))
        box = self._box()
        if box:
            tr, w, h = box
            p.save()
            p.setTransform(tr, True)
            p.setPen(QPen(QColor(ACCENT), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRectF(-w / 2, -h / 2, w, h))
            p.drawLine(QPointF(0, -h / 2), QPointF(0, -h / 2 - 26 + HANDLE))
            p.restore()
            for name, pt in self._handles().items():
                p.setPen(QPen(QColor(ACCENT), 1.5))
                p.setBrush(QColor('#ffffff'))
                if name == 'rot':
                    p.drawEllipse(pt, HANDLE, HANDLE)
                else:
                    p.drawRect(QRectF(pt.x() - HANDLE + 1, pt.y() - HANDLE + 1, 2 * HANDLE - 2, 2 * HANDLE - 2))

    # ---- mouse

    def _handle_at(self, pos):
        for name, pt in self._handles().items():
            if abs(pos.x() - pt.x()) <= HANDLE + 3 and abs(pos.y() - pt.y()) <= HANDLE + 3:
                return name
        return None

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        pos = e.position()
        handle = self._handle_at(pos)
        clip = self.doc.selected()
        tl = self.doc.timeline
        if handle and clip:
            self.doc.checkpoint()
            c = self._box()[0].map(QPointF(0, 0))
            self._drag = {'mode': 'rotate' if handle == 'rot' else 'scale', 'clip': clip, 'c': c,
                          'start': pos, 'scale': clip.scale, 'rotation': clip.rotation,
                          'angle0': math.degrees(math.atan2(pos.y() - c.y(), pos.x() - c.x()))}
            return
        pt = self._to_canvas(pos)
        hit = None
        for cl in reversed(tl.active(self.doc.time)):
            if clip_bounds(cl, self.doc.time - cl.start, tl.width, tl.height).contains(pt):
                hit = cl
                break
        self.doc.select(hit)
        if hit:
            self.doc.checkpoint()
            self._drag = {'mode': 'move', 'clip': hit, 'start': pos, 'x': hit.x, 'y': hit.y}
        self.update()

    def mouseMoveEvent(self, e):
        pos = e.position()
        d = self._drag
        if not d:
            h = self._handle_at(pos)
            self.setCursor(Qt.CursorShape.CrossCursor if h == 'rot' else
                           Qt.CursorShape.SizeFDiagCursor if h in ('tl', 'br') else
                           Qt.CursorShape.SizeBDiagCursor if h in ('tr', 'bl') else Qt.CursorShape.ArrowCursor)
            return
        clip = d['clip']
        tl = self.doc.timeline
        k = self._k()
        free = bool(e.modifiers() & Qt.KeyboardModifier.AltModifier)
        if d['mode'] == 'move':
            nx = d['x'] + (pos.x() - d['start'].x()) / k / tl.width
            ny = d['y'] + (pos.y() - d['start'].y()) / k / tl.height
            gx = not free and abs(nx - 0.5) * tl.width * k < SNAP_PX
            gy = not free and abs(ny - 0.5) * tl.height * k < SNAP_PX
            clip.x, clip.y = (0.5 if gx else nx), (0.5 if gy else ny)
            self._guides = (gx, gy)
        elif d['mode'] == 'scale':
            c = d['c']
            d0 = max(1.0, math.hypot(d['start'].x() - c.x(), d['start'].y() - c.y()))
            d1 = math.hypot(pos.x() - c.x(), pos.y() - c.y())
            clip.scale = max(0.01, d['scale'] * d1 / d0)
        else:
            c = d['c']
            a = math.degrees(math.atan2(pos.y() - c.y(), pos.x() - c.x()))
            rot = (d['rotation'] + a - d['angle0'] + 180) % 360 - 180
            if not free:
                nearest = round(rot / 45) * 45
                if abs(rot - nearest) < 4:
                    rot = nearest
            clip.rotation = rot
        self.doc.notify()

    def mouseReleaseEvent(self, _):
        self._drag = None
        self._guides = (False, False)
        self.update()


class PlayerPanel(QWidget):
    canvas_size_changed = Signal()
    ready_changed = Signal()

    def __init__(self, doc: Document):
        super().__init__()
        self.doc = doc
        self.playing = False
        self.quality = 1.0
        self.cache = FrameCache()
        doc.cache = self.cache
        doc.ready_ranges = []
        self._play_t0 = 0.0
        self._play_from = 0.0

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 8)
        lay.setSpacing(6)
        head = QHBoxLayout()
        title = QLabel('Player')
        title.setProperty('heading', True)
        head.addWidget(title)
        head.addStretch(1)
        self.bg_combo = QComboBox()
        self.bg_combo.addItems(['Checkerboard', 'Black', 'White', 'Green', 'Background picture…'])
        self.bg_combo.setToolTip('What shows behind the stickers in the preview. Never exported.')
        self.quality_combo = QComboBox()
        self.quality_combo.addItems([q for q, _ in QUALITY])
        head.addWidget(self.bg_combo)
        head.addWidget(self.quality_combo)
        lay.addLayout(head)

        self.canvas = Canvas(doc, self)
        lay.addWidget(self.canvas, 1)

        srow = QHBoxLayout()
        self.scrub = QSlider(Qt.Orientation.Horizontal)
        self.scrub.setObjectName('scrub')
        self.scrub.setRange(0, 10000)
        self.time_label = QLabel()
        self.time_label.setStyleSheet('background:#23252b; border-radius:6px; padding:4px 10px;')
        self.total_label = QLabel()
        self.total_label.setProperty('muted', True)
        srow.addWidget(self.scrub, 1)
        srow.addWidget(self.time_label)
        srow.addWidget(QLabel('/'))
        srow.addWidget(self.total_label)
        lay.addLayout(srow)

        trow = QHBoxLayout()
        self.btn_prev = self._tool('prev', 'Previous frame  (←)')
        self.btn_next = self._tool('next', 'Next frame  (→)')
        self.btn_play = self._tool('play', 'Play / pause  (Space)')
        self.btn_stop = self._tool('stop', 'Stop and go to start')
        for b in (self.btn_prev, self.btn_next, self.btn_play, self.btn_stop):
            trow.addWidget(b)
        self.loop_btn = QToolButton()
        self.loop_btn.setText('⟲')
        self.loop_btn.setCheckable(True)
        self.loop_btn.setToolTip('Repeat playback')
        trow.addWidget(self.loop_btn)
        trow.addStretch(1)
        self.ready_label = QLabel()
        self.ready_label.setProperty('muted', True)
        trow.addWidget(self.ready_label)
        self.aspect = QComboBox()
        self.aspect.addItems([a for a, _, _ in ASPECTS])
        self.aspect.setToolTip('Video size')
        trow.addWidget(self.aspect)
        self.btn_snap = self._tool('camera', 'Save this frame as a PNG')
        self.btn_full = self._tool('fullscreen', 'Bigger preview')
        trow.addWidget(self.btn_snap)
        trow.addWidget(self.btn_full)
        lay.addLayout(trow)

        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self._tick)
        self.idle = QTimer(self)
        self.idle.setSingleShot(True)
        self.idle.timeout.connect(self._prerender_step)
        self.btn_play.clicked.connect(self.toggle)
        self.btn_stop.clicked.connect(self.stop_to_start)
        self.btn_prev.clicked.connect(lambda: self.step(-1))
        self.btn_next.clicked.connect(lambda: self.step(1))
        self.scrub.valueChanged.connect(self._scrubbed)
        self.bg_combo.currentIndexChanged.connect(self._bg)
        self.quality_combo.currentIndexChanged.connect(self._quality)
        self.aspect.currentIndexChanged.connect(self._aspect)
        self.btn_snap.clicked.connect(self.snapshot)
        doc.changed.connect(self._timeline_changed)
        doc.time_changed.connect(self.refresh)
        doc.selection_changed.connect(self.canvas.update)
        self._timeline_changed()

    def _tool(self, name, tip):
        b = QToolButton()
        b.setIcon(icon(name))
        b.setIconSize(QSize(22, 22))
        b.setToolTip(tip)
        return b

    # ---- frames

    def preview_width(self) -> int:
        tl = self.doc.timeline
        w = int(self.canvas.canvas_rect().width() * self.devicePixelRatioF() * self.quality)
        return max(64, min(tl.width, w))

    def frame_index(self, t: float | None = None) -> int:
        t = self.doc.time if t is None else t
        return int(math.floor(t * self.doc.timeline.fps + 1e-6))

    def _frame(self, index: int, width: int) -> QImage:
        tl = self.doc.timeline
        key = self.cache.key(tl, index, width)
        img = self.cache.get(key)
        if img is None:
            img = render_timeline(tl, index / tl.fps, width)
            self.cache.put(key, img)
        return img

    def _timeline_changed(self):
        self.cache.refresh_fingerprints(self.doc.timeline)
        self.refresh()
        self._schedule_prerender(250)

    def refresh(self):
        doc = self.doc
        tl = doc.timeline
        try:
            self.canvas.frame = self._frame(self.frame_index(), self.preview_width())
        except Exception as exc:          # keep the window alive
            self.ready_label.setText(f'Could not draw: {exc}')
        dur = tl.duration()
        self.time_label.setText(timecode(doc.time, tl.fps))
        self.total_label.setText(timecode(dur, tl.fps))
        self.scrub.blockSignals(True)
        self.scrub.setValue(int(round(10000 * doc.time / dur)) if dur else 0)
        self.scrub.blockSignals(False)
        idx = next((i for i, (_, w, h) in enumerate(ASPECTS) if (w, h) == (tl.width, tl.height)), -1)
        if idx >= 0 and idx != self.aspect.currentIndex():
            self.aspect.blockSignals(True)
            self.aspect.setCurrentIndex(idx)
            self.aspect.blockSignals(False)
        self.canvas.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, self.refresh)
        self._schedule_prerender(400)

    # ---- pre-rendering ahead of the playhead

    def _schedule_prerender(self, ms):
        if not self.playing:
            self.idle.start(ms)

    def prerender_all(self, budget_s: float = 30.0):
        """Fill the cache for the whole video (used by tests)."""
        end = time.perf_counter() + budget_s
        while time.perf_counter() < end:
            if self._prerender_step(loop=False):
                return True
        return False

    def _prerender_step(self, loop: bool = True) -> bool:
        """Render uncached frames ahead of the playhead for ~10 ms, then yield.
        Returns True when every frame is ready."""
        if self.playing:
            return False
        tl = self.doc.timeline
        width = self.preview_width()
        total = tl.frame_count()
        start = self.frame_index()
        t0 = time.perf_counter()
        done_all = True
        for n in range(total):
            i = (start + n) % total
            key = self.cache.key(tl, i, width)
            if self.cache.has(key):
                continue
            if self.cache.bytes > self.cache.budget * 0.92:
                break
            self.cache.put(key, render_timeline(tl, i / tl.fps, width))
            if time.perf_counter() - t0 > 0.010:
                done_all = False
                break
        now = time.perf_counter()
        if done_all or now - getattr(self, '_ready_at', 0) > 0.25:
            self._ready_at = now
            self._update_ready(width)
        if not done_all and loop:
            self.idle.start(1)
        return done_all

    def _update_ready(self, width):
        tl = self.doc.timeline
        total = tl.frame_count()
        ranges, run = [], None
        ready = 0
        for i in range(total):
            ok = self.cache.has(self.cache.key(tl, i, width))
            ready += ok
            if ok and run is None:
                run = i
            elif not ok and run is not None:
                ranges.append((run / tl.fps, i / tl.fps))
                run = None
        if run is not None:
            ranges.append((run / tl.fps, total / tl.fps))
        self.doc.ready_ranges = ranges
        pct = int(100 * ready / max(1, total))
        self.ready_label.setText('Ready to play' if pct >= 100 else f'Preparing preview… {pct}%')
        self.ready_changed.emit()

    # ---- transport

    def toggle(self):
        if self.playing:
            self.pause()
        else:
            if self.doc.time >= self.doc.timeline.duration() - 1e-6:
                self.doc.set_time(0)
            self.playing = True
            self.idle.stop()
            self.btn_play.setIcon(icon('pause'))
            self._play_t0 = time.perf_counter()
            self._play_from = self.doc.time
            self.timer.start(max(2, int(500 / self.doc.timeline.fps)))     # poll twice per frame
            self.canvas.update()

    def pause(self):
        if self.playing:
            self.playing = False
            self.btn_play.setIcon(icon('play'))
            self.timer.stop()
            self.canvas.update()
            self._schedule_prerender(200)

    def stop_to_start(self):
        self.pause()
        self.doc.set_time(0)

    def step(self, n):
        self.pause()
        fps = self.doc.timeline.fps
        self.doc.set_time((self.frame_index() + n) / fps)

    def _tick(self):
        tl = self.doc.timeline
        t = self._play_from + (time.perf_counter() - self._play_t0)
        dur = tl.duration()
        if t >= dur:
            if self.loop_btn.isChecked():
                self._play_t0 = time.perf_counter()
                self._play_from = 0.0
                t = 0.0
            else:
                self.doc.set_time(dur)
                self.pause()
                return
        # Show the frame for this exact moment; nothing to do if it is already shown.
        snapped = self.frame_index(t) / tl.fps
        if abs(snapped - self.doc.time) > 1e-9:
            self.doc.set_time(snapped)

    def _scrubbed(self, v):
        self.doc.set_time(v / 10000 * self.doc.timeline.duration())

    # ---- options

    def _bg(self, i):
        names = ['checker', '#000000', '#ffffff', '#00b140', 'image']
        if names[i] == 'image':
            path, _ = QFileDialog.getOpenFileName(self, 'Background picture (preview only)', '',
                                                  'Pictures (*.png *.jpg *.jpeg *.webp *.bmp)')
            img = QImage(path) if path else QImage()
            if img.isNull():
                self.bg_combo.setCurrentIndex(0)
                return
            self.canvas.bg_image = img
        self.canvas.background = names[i]
        self.canvas.update()

    def _quality(self, i):
        self.quality = QUALITY[i][1]
        self.refresh()
        self._schedule_prerender(100)

    def _aspect(self, i):
        _, w, h = ASPECTS[i]
        tl = self.doc.timeline
        if (w, h) == (tl.width, tl.height):
            return
        self.doc.checkpoint()
        k = w / tl.width
        for c in tl.clips:
            c.scale *= k
        tl.width, tl.height = w, h
        self.doc.notify()
        self.canvas_size_changed.emit()

    def snapshot(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Save frame', 'frame.png', 'PNG (*.png)')
        if path:
            render_timeline(self.doc.timeline, self.frame_index() / self.doc.timeline.fps).save(path)

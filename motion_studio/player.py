"""Top-centre player: preview, scrubber, timecode and transport buttons."""
from __future__ import annotations

import time

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel, QSlider, QToolButton,
                               QVBoxLayout, QWidget)

from .document import Document
from .theme import ACCENT, BG, MUTED, TEXT, icon
from .timeline import clip_bounds, render_timeline

ASPECTS = [('16:9', 1920, 1080), ('9:16', 1080, 1920), ('1:1', 1080, 1080), ('4:5', 1080, 1350),
           ('4K 16:9', 3840, 2160)]
QUALITY = [('Full Quality', 1.0), ('1/2', 0.5), ('1/4', 0.25)]


def timecode(t: float, fps: float) -> str:
    total_frames = int(round(t * fps))
    f = total_frames % int(round(fps))
    s = int(total_frames // fps)
    return f'{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}:{f:02d}'


class Canvas(QWidget):
    """The picture. Click a sticker to select it; drag to move it."""

    def __init__(self, doc: Document, player: 'PlayerPanel'):
        super().__init__()
        self.doc = doc
        self.player = player
        self.frame: QImage | None = None
        self.background = 'checker'
        self.bg_image: QImage | None = None
        self._drag = None
        self.setMinimumSize(360, 200)

    def canvas_rect(self) -> QRectF:
        tl = self.doc.timeline
        w, h = self.width() - 12, self.height() - 12
        k = min(w / tl.width, h / tl.height)
        cw, ch = tl.width * k, tl.height * k
        return QRectF((self.width() - cw) / 2, (self.height() - ch) / 2, cw, ch)

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
        clip = self.doc.selected()
        tl = self.doc.timeline
        if clip and clip.start <= self.doc.time < clip.end and not self.player.playing:
            b = clip_bounds(clip, self.doc.time - clip.start, tl.width, tl.height)
            k = r.width() / tl.width
            box = QRectF(r.left() + b.left() * k, r.top() + b.top() * k, b.width() * k, b.height() * k)
            p.setPen(QPen(QColor(ACCENT), 1.5, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(box)

    def _to_canvas(self, pos):
        r = self.canvas_rect()
        tl = self.doc.timeline
        return (pos.x() - r.left()) / r.width() * tl.width, (pos.y() - r.top()) / r.height() * tl.height

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        x, y = self._to_canvas(e.position())
        tl = self.doc.timeline
        hit = None
        for clip in reversed(tl.active(self.doc.time)):
            if clip_bounds(clip, self.doc.time - clip.start, tl.width, tl.height).contains(x, y):
                hit = clip
                break
        self.doc.select(hit)
        if hit:
            self.doc.checkpoint()
            self._drag = (x, y, hit.x, hit.y)
        self.update()

    def mouseMoveEvent(self, e):
        clip = self.doc.selected()
        if self._drag and clip:
            sx, sy, ox, oy = self._drag
            x, y = self._to_canvas(e.position())
            tl = self.doc.timeline
            clip.x = ox + (x - sx) / tl.width
            clip.y = oy + (y - sy) / tl.height
            self.doc.notify()

    def mouseReleaseEvent(self, _):
        self._drag = None


class PlayerPanel(QWidget):
    canvas_size_changed = Signal()

    def __init__(self, doc: Document):
        super().__init__()
        self.doc = doc
        self.playing = False
        self._last = 0.0
        self.quality = 1.0

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
        self.scrub.setRange(0, 1000)
        self.time_label = QLabel()
        self.time_label.setStyleSheet(f'background:#23252b; border-radius:6px; padding:4px 10px;')
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
        trow.addStretch(1)
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
        self.timer.timeout.connect(self._tick)
        self.btn_play.clicked.connect(self.toggle)
        self.btn_stop.clicked.connect(self.stop_to_start)
        self.btn_prev.clicked.connect(lambda: self.step(-1))
        self.btn_next.clicked.connect(lambda: self.step(1))
        self.scrub.valueChanged.connect(self._scrubbed)
        self.bg_combo.currentIndexChanged.connect(self._bg)
        self.quality_combo.currentIndexChanged.connect(self._quality)
        self.aspect.currentIndexChanged.connect(self._aspect)
        self.btn_snap.clicked.connect(self.snapshot)
        doc.changed.connect(self.refresh)
        doc.time_changed.connect(self.refresh)
        doc.selection_changed.connect(self.canvas.update)

    def _tool(self, name, tip):
        b = QToolButton()
        b.setIcon(icon(name))
        b.setIconSize(QSize(22, 22))
        b.setToolTip(tip)
        return b

    # ---- drawing

    def refresh(self):
        doc = self.doc
        tl = doc.timeline
        width = int(self.canvas.canvas_rect().width() * self.devicePixelRatioF() * self.quality)
        width = max(64, min(tl.width, width))
        self.canvas.frame = render_timeline(tl, doc.time, width)
        dur = tl.duration()
        self.time_label.setText(timecode(doc.time, tl.fps))
        self.total_label.setText(timecode(dur, tl.fps))
        self.scrub.blockSignals(True)
        self.scrub.setValue(int(round(1000 * doc.time / dur)) if dur else 0)
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

    # ---- transport

    def toggle(self):
        if self.playing:
            self.pause()
        else:
            if self.doc.time >= self.doc.timeline.duration() - 1e-6:
                self.doc.set_time(0)
            self.playing = True
            self.btn_play.setIcon(icon('pause'))
            self._last = time.perf_counter()
            self.timer.start(max(5, int(1000 / self.doc.timeline.fps)))

    def pause(self):
        self.playing = False
        self.btn_play.setIcon(icon('play'))
        self.timer.stop()
        self.canvas.update()

    def stop_to_start(self):
        self.pause()
        self.doc.set_time(0)

    def step(self, n):
        self.pause()
        fps = self.doc.timeline.fps
        self.doc.set_time(round(self.doc.time * fps + n) / fps)

    def _tick(self):
        now = time.perf_counter()
        t = self.doc.time + (now - self._last)
        self._last = now
        dur = self.doc.timeline.duration()
        if t >= dur:
            t = dur
            self.pause()
        self.doc.set_time(t)

    def _scrubbed(self, v):
        self.doc.set_time(v / 1000 * self.doc.timeline.duration())

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
            render_timeline(self.doc.timeline, self.doc.time).save(path)

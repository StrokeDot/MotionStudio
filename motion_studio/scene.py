"""Sticker sources: pictures, SVGs (files or built-in), animated GIFs and text."""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QImage, QImageReader,
                           QPainter, QPainterPath, QPen)
from PySide6.QtSvg import QSvgRenderer


import threading

_RENDER_LOCK = threading.RLock()

RASTER_EXT = {'.png', '.jpg', '.jpeg', '.bmp', '.webp', '.tif', '.tiff'}
ANIMATED_EXT = {'.gif', '.webp', '.apng'}
SVG_EXT = {'.svg'}


# ---------------------------------------------------------------- the object


@dataclass
class TextStyle:
    text: str = 'Your text'
    family: str = 'Segoe UI'
    size: float = 120.0
    bold: bool = True
    italic: bool = False
    color: str = '#ffffff'
    outline_color: str = '#000000'
    outline_width: float = 6.0


@dataclass
class ObjectSource:
    kind: str = 'text'           # 'image', 'svg', 'animated', 'text'
    path: str = ''
    text: TextStyle = field(default_factory=TextStyle)

    def __post_init__(self):
        self._cache_key = None
        self._raster: QImage | None = None
        self._svg: QSvgRenderer | None = None
        self._frames: list[tuple[QImage, float]] = []
        self._rendered: dict = {}

    # ---- loading

    @staticmethod
    def from_file(path: str) -> 'ObjectSource':
        ext = os.path.splitext(path)[1].lower()
        if ext in SVG_EXT:
            kind = 'svg'
        else:
            reader = QImageReader(path)
            kind = 'animated' if (ext in ANIMATED_EXT and reader.supportsAnimation()
                                  and reader.imageCount() != 1) else 'image'
        src = ObjectSource(kind=kind, path=path)
        src.load()
        return src

    def load(self) -> None:
        self._rendered.clear()
        self._raster, self._svg, self._frames = None, None, []
        if self.kind == 'image':
            img = QImage(self.path)
            if img.isNull():
                raise ValueError(f'Could not open the picture: {self.path}')
            self._raster = img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        elif self.kind == 'svg':
            if self.path.startswith('builtin:'):
                from .stickers import builtin_svg
                r = QSvgRenderer(QByteArray(builtin_svg(self.path[8:]).encode()))
            else:
                r = QSvgRenderer(self.path)
            if not r.isValid():
                raise ValueError(f'Could not open the SVG: {self.path}')
            self._svg = r
        elif self.kind == 'animated':
            reader = QImageReader(self.path)
            while True:
                img = reader.read()
                if img.isNull():
                    break
                delay = reader.nextImageDelay() / 1000.0 or 0.1
                self._frames.append((img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied),
                                     max(0.02, delay)))
            if not self._frames:
                raise ValueError(f'Could not open the animation: {self.path}')

    # ---- size in "native" pixels

    def native_size(self) -> tuple[float, float]:
        if self.kind == 'image' and self._raster is not None:
            return float(self._raster.width()), float(self._raster.height())
        if self.kind == 'svg' and self._svg is not None:
            s = self._svg.defaultSize()
            if s.width() > 0 and s.height() > 0:
                return float(s.width()), float(s.height())
            vb = self._svg.viewBoxF()
            return max(1.0, vb.width()), max(1.0, vb.height())
        if self.kind == 'animated' and self._frames:
            img = self._frames[0][0]
            return float(img.width()), float(img.height())
        if self.kind == 'text':
            return self._text_path_box()[1:3]
        return 100.0, 100.0

    # ---- pictures

    def _text_font(self) -> QFont:
        st = self.text
        f = QFont(st.family)
        f.setPixelSize(max(1, int(round(st.size))))
        f.setBold(st.bold)
        f.setItalic(st.italic)
        return f

    def _text_path_box(self):
        st = self.text
        font = self._text_font()
        fm = QFontMetricsF(font)
        path = QPainterPath()
        lines = (st.text or ' ').split('\n')
        line_h = fm.height()
        for i, line in enumerate(lines):
            w = fm.horizontalAdvance(line)
            path.addText(QPointF(-w / 2, fm.ascent() + i * line_h), font, line)
        pad = st.outline_width + 4
        r = path.boundingRect() if not path.isEmpty() else QRectF(0, 0, 10, 10)
        return path, r.width() + 2 * pad, r.height() + 2 * pad, r, pad

    def image_at(self, seconds: float, pixel_scale: float) -> QImage:
        """The object's picture at time `seconds`, sharp enough to be drawn
        at `pixel_scale` output pixels per native pixel."""
        if self.kind == 'image':
            return self._raster
        if self.kind == 'animated':
            total = sum(d for _, d in self._frames)
            t = seconds % total if total > 0 else 0
            for img, d in self._frames:
                if t < d:
                    return img
                t -= d
            return self._frames[-1][0]
        # Vector kinds: render once per power-of-two size and let the painter scale
        # the rest. A zoom or pop then reuses one sharp picture instead of
        # re-rasterising on every frame (which caused stutter).
        need = min(8.0, max(0.125, pixel_scale))
        k = 2.0 ** (math.ceil(math.log2(need) * 2 - 1e-9) / 2)      # steps of ×1.41
        key = (self.kind, k, tuple(self.text.__dict__.values()) if self.kind == 'text' else None)
        with _RENDER_LOCK:
            if key in self._rendered:
                return self._rendered[key]
        w, h = self.native_size()
        img = QImage(max(1, int(math.ceil(w * k))), max(1, int(math.ceil(h * k))),
                     QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        if self.kind == 'svg':
            self._svg.render(p, QRectF(0, 0, img.width(), img.height()))
        else:
            path, _, _, r, pad = self._text_path_box()
            p.scale(k, k)
            p.translate(pad - r.left(), pad - r.top())
            st = self.text
            if st.outline_width > 0:
                pen = QPen(QColor(st.outline_color), st.outline_width * 2)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                p.strokePath(path, pen)
            p.fillPath(path, QBrush(QColor(st.color)))
        p.end()
        with _RENDER_LOCK:
            if len(self._rendered) > 12:
                self._rendered.clear()
            self._rendered[key] = img
        return img

    def label(self) -> str:
        if self.kind == 'text':
            return (self.text.text or 'Text').split('\n')[0][:40]
        if self.path.startswith('builtin:'):
            return self.path[8:].replace('_', ' ').title()
        return os.path.basename(self.path)

    def clone(self) -> 'ObjectSource':
        return ObjectSource.from_dict(self.to_dict())

    def to_dict(self) -> dict:
        return {'kind': self.kind, 'path': self.path, 'text': dict(self.text.__dict__)}

    @classmethod
    def from_dict(cls, d: dict) -> 'ObjectSource':
        src = cls(kind=d.get('kind', 'text'), path=d.get('path', ''),
                  text=TextStyle(**{k: v for k, v in (d.get('text') or {}).items()
                                    if k in TextStyle.__dataclass_fields__}))
        if src.kind != 'text':
            src.load()
        return src



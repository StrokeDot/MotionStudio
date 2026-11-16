"""The object being animated, the project settings, and frame rendering.

`render_frame` is the single place pictures are made. The preview and the
export both call it, so what you see is exactly what gets exported.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QImage, QImageReader,
                           QPainter, QPainterPath, QPen)
from PySide6.QtSvg import QSvgRenderer

from .effects import OPPOSITE, Animation, Transform, entrance, exit_, loop, swing_pivot

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
        # Vector kinds: render at the needed resolution (cached per size).
        k = min(8.0, max(0.05, pixel_scale))
        k = round(k * 8) / 8 or 0.125
        key = (self.kind, k, tuple(self.text.__dict__.values()) if self.kind == 'text' else None)
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
        if len(self._rendered) > 24:
            self._rendered.clear()
        self._rendered[key] = img
        return img

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


# ---------------------------------------------------------------- the project


@dataclass
class Project:
    width: int = 1920
    height: int = 1080
    fps: float = 30.0
    duration: float = 4.0
    source: ObjectSource = field(default_factory=ObjectSource)
    x: float = 0.5               # object centre, as a fraction of the canvas
    y: float = 0.5
    scale: float = 1.0           # output pixels per native pixel at 1080p-wide canvas
    rotation: float = 0.0
    opacity: float = 1.0
    animation: Animation = field(default_factory=Animation)

    # ---- timing

    def in_end(self) -> float:
        a = self.animation.in_
        return min(self.duration, a.duration) if a.effect != 'None' else 0.0

    def out_start(self) -> float:
        a = self.animation.out
        if a.effect == 'None':
            return self.duration
        return max(self.in_end(), self.duration - a.duration)

    def frame_count(self) -> int:
        return max(1, int(round(self.duration * self.fps)))

    # ---- geometry

    def object_size(self) -> tuple[float, float]:
        w, h = self.source.native_size()
        return w * self.scale, h * self.scale

    def fit_object(self, fraction: float = 0.5) -> None:
        w, h = self.source.native_size()
        if not (w and h):
            self.scale = 1.0
            return
        fit = min(fraction * self.height / h, fraction * self.width / w)
        # Vectors scale up sharply; pictures are never enlarged past their own pixels.
        self.scale = fit if self.source.kind == 'svg' else min(1.0, fit)

    def travel(self, direction: str) -> float:
        """Distance that puts the object just off-screen when it starts behind its
        place, travelling in `direction`."""
        from .effects import DIRECTIONS
        vx, vy = DIRECTIONS.get(direction, (0.0, -1.0))
        w, h = self.object_size()
        # Use the rotated bounding box so a tilted object also clears the edge.
        a = math.radians(self.rotation)
        bw = abs(w * math.cos(a)) + abs(h * math.sin(a))
        bh = abs(w * math.sin(a)) + abs(h * math.cos(a))
        cx, cy = self.x * self.width, self.y * self.height
        need = []
        if vx > 1e-6:
            need.append((cx + bw / 2) / vx)
        elif vx < -1e-6:
            need.append((self.width - cx + bw / 2) / -vx)
        if vy > 1e-6:
            need.append((cy + bh / 2) / vy)
        elif vy < -1e-6:
            need.append((self.height - cy + bh / 2) / -vy)
        return (min(need) if need else 0.0) * 1.02 + 2

    def transforms_at(self, t: float) -> tuple[Transform, Transform]:
        """(motion transform, loop transform) at time t."""
        anim = self.animation
        move = Transform()
        ie, os_ = self.in_end(), self.out_start()
        if anim.in_.effect != 'None' and t < ie:
            move = entrance(anim.in_, t / max(1e-6, ie), self.travel(anim.in_.direction))
        if anim.out.effect != 'None' and t > os_:
            span = max(1e-6, self.duration - os_)
            move = move.combine(exit_(anim.out, (t - os_) / span,
                                      self.travel(OPPOSITE.get(anim.out.direction, 'down'))))
        w, h = self.object_size()
        lp = loop(anim.loop, t, max(w, h))
        return move, lp

    def to_dict(self) -> dict:
        return {'width': self.width, 'height': self.height, 'fps': self.fps,
                'duration': self.duration, 'source': self.source.to_dict(),
                'x': self.x, 'y': self.y, 'scale': self.scale, 'rotation': self.rotation,
                'opacity': self.opacity, 'animation': self.animation.to_dict()}

    @classmethod
    def from_dict(cls, d: dict) -> 'Project':
        p = cls()
        for k in ('width', 'height', 'fps', 'duration', 'x', 'y', 'scale', 'rotation', 'opacity'):
            if k in d:
                setattr(p, k, type(getattr(p, k))(d[k]))
        p.source = ObjectSource.from_dict(d.get('source') or {})
        p.animation = Animation.from_dict(d.get('animation') or {})
        return p


# ---------------------------------------------------------------- rendering


def _blurred(img: QImage, radius: float) -> QImage:
    """Gaussian blur with Pillow, padding the picture so the blur can spread."""
    from PIL import Image, ImageFilter
    pad = int(math.ceil(radius * 2.5))
    src = img.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = src.width(), src.height()
    pil = Image.frombuffer('RGBA', (w, h), bytes(src.constBits()), 'raw', 'RGBA',
                           src.bytesPerLine(), 1)
    canvas = Image.new('RGBA', (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    canvas.paste(pil, (pad, pad))
    # Blur premultiplied colour so transparent edges do not turn dark.
    premul = canvas.convert('RGBa').filter(ImageFilter.GaussianBlur(radius)).convert('RGBA')
    data = premul.tobytes()
    out = QImage(data, premul.width, premul.height, premul.width * 4, QImage.Format.Format_RGBA8888)
    return out.copy(), pad


def render_frame(project: Project, t: float, out_width: int | None = None) -> QImage:
    """Render the frame at time `t` (seconds) on a transparent canvas.

    `out_width` renders a smaller copy (for the preview); None = full size.
    """
    out_w = out_width or project.width
    f = out_w / project.width
    out_h = max(1, int(round(project.height * f)))
    frame = QImage(out_w, out_h, QImage.Format.Format_ARGB32_Premultiplied)
    frame.fill(Qt.GlobalColor.transparent)

    move, lp = project.transforms_at(t)
    swing = swing_pivot(project.animation.loop)
    total = move if swing else move.combine(lp)
    if swing:
        total.dx += lp.dx
        total.dy += lp.dy
        total.opacity *= lp.opacity
    opacity = max(0.0, min(1.0, project.opacity * total.opacity))
    if opacity <= 0.001 or abs(total.scale_x) < 1e-4 or abs(total.scale_y) < 1e-4 \
            or total.clip_fraction <= 0.0005:
        return frame

    nw, nh = project.source.native_size()
    pixel_scale = project.scale * f * max(abs(total.scale_x), abs(total.scale_y), 1.0)
    img = project.source.image_at(t, pixel_scale)
    draw_rect = QRectF(-nw / 2, -nh / 2, nw, nh)

    blur_px = total.blur * f
    if blur_px > 0.4:
        # Blur in the picture's own pixels, then grow the drawing rect to match.
        per_native = img.width() / nw
        radius = blur_px / max(1e-6, project.scale * f) * per_native
        img, pad = _blurred(img, radius)
        pn = pad / per_native
        draw_rect = QRectF(-nw / 2 - pn, -nh / 2 - pn, nw + 2 * pn, nh + 2 * pn)

    p = QPainter(frame)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
    p.setOpacity(opacity)
    cx = (project.x * project.width + total.dx) * f
    cy = (project.y * project.height + total.dy) * f
    p.translate(cx, cy)
    p.rotate(project.rotation + total.rotation)
    p.scale(project.scale * f * total.scale_x, project.scale * f * total.scale_y)
    if swing and lp.rotation:
        p.translate(0, -nh / 2)
        p.rotate(lp.rotation)
        p.translate(0, nh / 2)
    if total.clip_fraction < 1.0 and total.clip_from:
        p.setClipRect(_clip_rect(nw, nh, total.clip_fraction, total.clip_from))
    p.drawImage(draw_rect, img)
    p.end()
    return frame


def _clip_rect(w: float, h: float, frac: float, side: str) -> QRectF:
    """Visible part of the object: a band of `frac` anchored on `side`."""
    x0, y0, x1, y1 = -w / 2, -h / 2, w / 2, h / 2
    m = 2.0   # small margin so outlines are not shaved
    x0, y0, x1, y1 = x0 - m, y0 - m, x1 + m, y1 + m
    W, H = x1 - x0, y1 - y0
    if 'left' in side:
        x1 = x0 + W * frac
    if 'right' in side:
        x0 = x1 - W * frac
    if side.startswith('up'):
        y1 = y0 + H * frac
    if side.startswith('down'):
        y0 = y1 - H * frac
    return QRectF(QPointF(x0, y0), QPointF(x1, y1))

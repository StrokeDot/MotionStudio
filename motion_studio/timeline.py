"""The timeline: tracks of sticker clips, each with In/Out transitions and a
stack of effects, and the one function that renders a frame of it.

Preview and export both call `render_timeline`, so what you see is what you get.
"""
from __future__ import annotations

import copy
import itertools
import math
from dataclasses import dataclass, field

from PIL import Image, ImageChops, ImageFilter, ImageOps
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter

from .effects import (DIRECTIONS, IN_OUT_BY_NAME, OPPOSITE, Phase, Transform, entrance, exit_,
                      loop)
from .scene import ObjectSource

# ================================================================ catalogue

TRANSITION_CATEGORIES = {
    'Slide': ['Slide'],
    'Bounce': ['Bounce', 'Slow bounce', 'Squash drop'],
    'Zoom': ['Pop', 'Zoom'],
    'Fade & Blur': ['Fade', 'Blur'],
    'Spin & Flip': ['Spin', 'Flip'],
    'Wipe': ['Wipe'],
}


@dataclass
class Param:
    id: str
    label: str
    kind: str = 'float'        # 'float', 'int', 'color', 'direction', 'bool'
    min: float = 0
    max: float = 100
    default: object = 0


@dataclass
class EffectType:
    id: str
    name: str
    category: str              # 'Motion' or 'Look'
    params: list[Param]
    hint: str = ''


_SPEED = Param('cycle', 'Cycle length (s)', 'float', 0.1, 10, 1.5)
_AMOUNT = Param('amount', 'Strength', 'int', 1, 400, 100)

EFFECT_TYPES = [
    EffectType('float', 'Float', 'Motion', [Param('direction', 'Moves', 'direction', default='up'),
                                            _SPEED, _AMOUNT], 'Drifts gently back and forth.'),
    EffectType('hop', 'Hop', 'Motion', [Param('direction', 'Moves', 'direction', default='up'),
                                        Param('cycle', 'Cycle length (s)', 'float', 0.1, 10, 0.8), _AMOUNT],
               'Keeps hopping.'),
    EffectType('pulse', 'Pulse', 'Motion', [Param('cycle', 'Cycle length (s)', 'float', 0.1, 10, 1.0), _AMOUNT],
               'Grows and shrinks like a heartbeat.'),
    EffectType('wiggle', 'Wiggle', 'Motion', [Param('cycle', 'Cycle length (s)', 'float', 0.1, 10, 0.6), _AMOUNT],
               'Tilts left and right.'),
    EffectType('swing', 'Swing', 'Motion', [_SPEED, _AMOUNT], 'Swings from its top edge.'),
    EffectType('spin', 'Spin', 'Motion', [Param('direction', 'Turns', 'direction', default='right'),
                                          Param('cycle', 'Seconds per turn', 'float', 0.1, 20, 3.0)],
               'Turns round continuously.'),
    EffectType('shake', 'Shake', 'Motion', [Param('cycle', 'Cycle length (s)', 'float', 0.05, 5, 0.4), _AMOUNT],
               'Quick small shakes.'),
    EffectType('blink', 'Blink', 'Motion', [Param('cycle', 'Cycle length (s)', 'float', 0.1, 10, 1.0), _AMOUNT],
               'Fades down and up.'),
    EffectType('shadow', 'Drop Shadow', 'Look', [
        Param('distance', 'Distance', 'float', 0, 200, 18), Param('angle', 'Direction (°)', 'float', 0, 360, 45),
        Param('softness', 'Softness', 'float', 0, 100, 14), Param('opacity', 'Opacity', 'int', 0, 100, 60),
        Param('color', 'Colour', 'color', default='#000000')], 'A shadow behind the sticker.'),
    EffectType('glow', 'Glow', 'Look', [
        Param('size', 'Size', 'float', 1, 150, 24), Param('strength', 'Strength', 'int', 0, 300, 120),
        Param('color', 'Colour', 'color', default='#ffd23f')], 'A soft coloured halo.'),
    EffectType('outline', 'Outline', 'Look', [
        Param('width', 'Width', 'float', 1, 60, 8), Param('color', 'Colour', 'color', default='#ffffff')],
        'A solid border around the shape.'),
    EffectType('tint', 'Tint', 'Look', [
        Param('amount', 'Amount', 'int', 0, 100, 60), Param('color', 'Colour', 'color', default='#3ab0ff')],
        'Colours the sticker.'),
    EffectType('bw', 'Black & White', 'Look', [Param('amount', 'Amount', 'int', 0, 100, 100)],
               'Removes the colour.'),
    EffectType('blur', 'Blur', 'Look', [Param('amount', 'Amount', 'float', 0, 100, 8)], 'Softens the sticker.'),
]
EFFECTS_BY_ID = {e.id: e for e in EFFECT_TYPES}


@dataclass
class EffectInstance:
    type: str
    enabled: bool = True
    params: dict = field(default_factory=dict)

    def __post_init__(self):
        et = EFFECTS_BY_ID[self.type]
        for p in et.params:
            self.params.setdefault(p.id, p.default)

    def info(self) -> EffectType:
        return EFFECTS_BY_ID[self.type]

    def reset(self):
        self.params = {p.id: p.default for p in self.info().params}

    def to_dict(self):
        return {'type': self.type, 'enabled': self.enabled, 'params': dict(self.params)}

    @classmethod
    def from_dict(cls, d):
        return cls(d['type'], bool(d.get('enabled', True)), dict(d.get('params') or {}))


# ================================================================ clips

_ids = itertools.count(1)


def _no_transition(direction='up') -> Phase:
    return Phase(effect='None', direction=direction, duration=1.0)


@dataclass
class Clip:
    source: ObjectSource
    start: float = 0.0
    duration: float = 4.0
    track: int = 0
    x: float = 0.5
    y: float = 0.5
    scale: float = 1.0
    rotation: float = 0.0
    opacity: float = 1.0
    trans_in: Phase = field(default_factory=_no_transition)
    trans_out: Phase = field(default_factory=_no_transition)
    effects: list[EffectInstance] = field(default_factory=list)
    id: int = field(default_factory=lambda: next(_ids))

    @property
    def end(self) -> float:
        return self.start + self.duration

    def name(self) -> str:
        return self.source.label()

    def in_end(self) -> float:
        return min(self.duration, self.trans_in.duration) if self.trans_in.effect != 'None' else 0.0

    def out_start(self) -> float:
        if self.trans_out.effect == 'None':
            return self.duration
        return max(self.in_end(), self.duration - self.trans_out.duration)

    def size(self) -> tuple[float, float]:
        w, h = self.source.native_size()
        return w * self.scale, h * self.scale

    def fit(self, canvas_w: int, canvas_h: int, fraction: float = 0.5):
        w, h = self.source.native_size()
        if not (w and h):
            return
        fit = min(fraction * canvas_h / h, fraction * canvas_w / w)
        self.scale = fit if self.source.kind in ('svg', 'text') else min(1.0, fit)

    def travel(self, direction: str, cw: int, ch: int) -> float:
        vx, vy = DIRECTIONS.get(direction, (0.0, -1.0))
        w, h = self.size()
        a = math.radians(self.rotation)
        bw = abs(w * math.cos(a)) + abs(h * math.sin(a))
        bh = abs(w * math.sin(a)) + abs(h * math.cos(a))
        # Look effects (shadow, glow) reach beyond the shape; leave room for them.
        extra = sum(_look_reach(e) for e in self.effects if e.enabled and e.info().category == 'Look')
        bw, bh = bw + 2 * extra, bh + 2 * extra
        cx, cy = self.x * cw, self.y * ch
        need = []
        if vx > 1e-6:
            need.append((cx + bw / 2) / vx)
        elif vx < -1e-6:
            need.append((cw - cx + bw / 2) / -vx)
        if vy > 1e-6:
            need.append((cy + bh / 2) / vy)
        elif vy < -1e-6:
            need.append((ch - cy + bh / 2) / -vy)
        return (min(need) if need else 0.0) * 1.02 + 2

    def motion_at(self, local: float, cw: int, ch: int) -> tuple[Transform, Transform, bool]:
        """(transition transform, motion-effect transform, swing-about-top?)"""
        move = Transform()
        ie, os_ = self.in_end(), self.out_start()
        if self.trans_in.effect != 'None' and local < ie:
            move = entrance(self.trans_in, local / max(1e-6, ie), self.travel(self.trans_in.direction, cw, ch))
        if self.trans_out.effect != 'None' and local > os_:
            span = max(1e-6, self.duration - os_)
            move = move.combine(exit_(self.trans_out, (local - os_) / span,
                                      self.travel(OPPOSITE.get(self.trans_out.direction, 'down'), cw, ch)))
        w, h = self.size()
        size = max(w, h)
        motion = Transform()
        swing_rot = 0.0
        for e in self.effects:
            if not e.enabled or e.info().category != 'Motion':
                continue
            p = e.params
            ph = Phase(effect=e.info().name, direction=str(p.get('direction', 'up')),
                       duration=float(p.get('cycle', 1.0)), amount=float(p.get('amount', 100)))
            t = loop(ph, local, size)
            if e.type == 'swing':
                swing_rot += t.rotation
                t.rotation = 0.0
            motion = motion.combine(t)
        return move, motion, swing_rot

    def clone(self) -> 'Clip':
        c = Clip.from_dict(self.to_dict())
        return c

    def to_dict(self) -> dict:
        return {'source': self.source.to_dict(), 'start': self.start, 'duration': self.duration,
                'track': self.track, 'x': self.x, 'y': self.y, 'scale': self.scale,
                'rotation': self.rotation, 'opacity': self.opacity,
                'trans_in': self.trans_in.to_dict(), 'trans_out': self.trans_out.to_dict(),
                'effects': [e.to_dict() for e in self.effects]}

    @classmethod
    def from_dict(cls, d: dict) -> 'Clip':
        c = cls(source=ObjectSource.from_dict(d.get('source') or {}))
        for k in ('start', 'duration', 'x', 'y', 'scale', 'rotation', 'opacity'):
            if k in d:
                setattr(c, k, float(d[k]))
        c.track = int(d.get('track', 0))
        c.trans_in = Phase.from_dict(d.get('trans_in'))
        c.trans_out = Phase.from_dict(d.get('trans_out'))
        c.effects = [EffectInstance.from_dict(e) for e in d.get('effects') or [] if e.get('type') in EFFECTS_BY_ID]
        return c


# ================================================================ timeline


@dataclass
class Timeline:
    width: int = 1920
    height: int = 1080
    fps: float = 30.0
    tracks: int = 3
    clips: list[Clip] = field(default_factory=list)
    hidden_tracks: set = field(default_factory=set)

    def duration(self) -> float:
        return max([1.0] + [c.end for c in self.clips])

    def frame_count(self) -> int:
        return max(1, int(round(self.duration() * self.fps)))

    def clip_by_id(self, cid):
        return next((c for c in self.clips if c.id == cid), None)

    def free_track_at(self, start: float, end: float) -> int:
        for t in range(self.tracks):
            if not any(c.track == t and c.start < end and c.end > start for c in self.clips):
                return t
        self.tracks += 1
        return self.tracks - 1

    def active(self, t: float) -> list[Clip]:
        return sorted((c for c in self.clips if c.start <= t < c.end and c.track not in self.hidden_tracks),
                      key=lambda c: c.track)

    def to_dict(self) -> dict:
        return {'width': self.width, 'height': self.height, 'fps': self.fps, 'tracks': self.tracks,
                'hidden_tracks': sorted(self.hidden_tracks), 'clips': [c.to_dict() for c in self.clips]}

    @classmethod
    def from_dict(cls, d: dict) -> 'Timeline':
        tl = cls(width=int(d.get('width', 1920)), height=int(d.get('height', 1080)),
                 fps=float(d.get('fps', 30)), tracks=int(d.get('tracks', 3)))
        tl.hidden_tracks = set(d.get('hidden_tracks') or [])
        tl.clips = [Clip.from_dict(c) for c in d.get('clips') or []]
        tl.tracks = max([tl.tracks] + [c.track + 1 for c in tl.clips])
        return tl


# ================================================================ look effects (Pillow)


def _look_reach(e: EffectInstance) -> float:
    p = e.params
    if e.type == 'shadow':
        return float(p['distance']) + float(p['softness']) * 2.5
    if e.type == 'glow':
        return float(p['size']) * 2.5
    if e.type == 'outline':
        return float(p['width']) + 2
    if e.type == 'blur':
        return float(p['amount']) * 2.5
    return 0.0


def _qimage_to_pil(img: QImage) -> Image.Image:
    src = img.convertToFormat(QImage.Format.Format_RGBA8888)
    return Image.frombuffer('RGBA', (src.width(), src.height()), bytes(src.constBits()), 'raw', 'RGBA',
                            src.bytesPerLine(), 1).copy()


def _pil_to_qimage(im: Image.Image) -> QImage:
    data = im.tobytes()
    return QImage(data, im.width, im.height, im.width * 4, QImage.Format.Format_RGBA8888).copy()


def _colour_layer(alpha: Image.Image, colour: str, opacity: float) -> Image.Image:
    c = QColor(colour)
    a = alpha.point(lambda v: int(min(255, v * opacity)))
    layer = Image.new('RGBA', alpha.size, (c.red(), c.green(), c.blue(), 0))
    layer.putalpha(a)
    return layer


def _blur_rgba(im: Image.Image, radius: float) -> Image.Image:
    if radius <= 0.3:
        return im
    return im.convert('RGBa').filter(ImageFilter.GaussianBlur(radius)).convert('RGBA')


def apply_looks(img: QImage, looks: list[EffectInstance], px_per_canvas: float) -> tuple[QImage, float]:
    """Apply look effects to the sticker picture. Sizes in effect settings are in
    canvas pixels; `px_per_canvas` converts them to this picture's pixels.
    Returns the new picture and the padding added on each side (picture pixels)."""
    if not looks:
        return img, 0.0
    k = px_per_canvas
    reach = sum(_look_reach(e) for e in looks) * k
    pad = int(math.ceil(reach)) + 2
    base = _qimage_to_pil(img)
    im = Image.new('RGBA', (base.width + 2 * pad, base.height + 2 * pad), (0, 0, 0, 0))
    im.paste(base, (pad, pad))
    for e in looks:
        p = e.params
        alpha = im.getchannel('A')
        if e.type == 'tint':
            c = QColor(p['color'])
            amt = float(p['amount']) / 100
            rgb = im.convert('RGB')
            # Colourise keeps light and dark areas: black stays black, white stays white.
            tinted = ImageOps.colorize(ImageOps.grayscale(rgb), black='#000000',
                                       mid=(c.red(), c.green(), c.blue()), white='#ffffff')
            mixed = Image.blend(rgb, tinted, amt)
            im = mixed.convert('RGBA')
            im.putalpha(alpha)
        elif e.type == 'bw':
            rgb = im.convert('RGB')
            mixed = Image.blend(rgb, ImageOps.grayscale(rgb).convert('RGB'), float(p['amount']) / 100)
            im = mixed.convert('RGBA')
            im.putalpha(alpha)
        elif e.type == 'blur':
            im = _blur_rgba(im, float(p['amount']) * k)
        elif e.type == 'outline':
            w = float(p['width']) * k
            grown = alpha.filter(ImageFilter.GaussianBlur(max(0.5, w / 2))).point(lambda v: 255 if v > 8 else int(v * 30))
            grown = ImageChops.lighter(grown, alpha.filter(ImageFilter.MaxFilter(3)))
            layer = _colour_layer(grown, p['color'], 1.0)
            layer.alpha_composite(im)
            im = layer
        elif e.type in ('shadow', 'glow'):
            if e.type == 'shadow':
                d = float(p['distance']) * k
                a = math.radians(float(p['angle']))     # direction the shadow falls; 90 = straight down
                dx, dy = int(round(math.cos(a) * d)), int(round(math.sin(a) * d))
                layer = _colour_layer(alpha, p['color'], float(p['opacity']) / 100)
                layer = _blur_rgba(layer, float(p['softness']) * k)
                shifted = Image.new('RGBA', im.size, (0, 0, 0, 0))
                shifted.paste(layer, (dx, dy))
                layer = shifted
            else:
                layer = _colour_layer(alpha, p['color'], 1.0)
                layer = _blur_rgba(layer, float(p['size']) * k)
                strength = float(p['strength']) / 100
                la = layer.getchannel('A').point(lambda v: int(min(255, v * strength)))
                layer.putalpha(la)
            layer.alpha_composite(im)
            im = layer
    return _pil_to_qimage(im), float(pad)


class _LookCache:
    def __init__(self):
        self.data = {}

    def get(self, img: QImage, looks, k):
        key = (img.cacheKey(), round(k, 3),
               tuple((e.type, tuple(sorted((a, str(b)) for a, b in e.params.items()))) for e in looks))
        hit = self.data.get(key)
        if hit is None:
            hit = apply_looks(img, looks, k)
            if len(self.data) > 64:
                self.data.clear()
            self.data[key] = hit
        return hit


LOOK_CACHE = _LookCache()


# ================================================================ rendering


def _clip_rect(w: float, h: float, frac: float, side: str) -> QRectF:
    m = 2.0
    x0, y0, x1, y1 = -w / 2 - m, -h / 2 - m, w / 2 + m, h / 2 + m
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


def draw_clip(p: QPainter, clip: Clip, local: float, cw: int, ch: int, f: float):
    """Draw one clip at its local time onto painter `p` (canvas scaled by f)."""
    move, motion, swing_rot = clip.motion_at(local, cw, ch)
    total = move.combine(motion)
    opacity = max(0.0, min(1.0, clip.opacity * total.opacity))
    if opacity <= 0.001 or abs(total.scale_x) < 1e-4 or abs(total.scale_y) < 1e-4 \
            or total.clip_fraction <= 0.0005:
        return
    nw, nh = clip.source.native_size()
    pixel_scale = clip.scale * f * max(abs(total.scale_x), abs(total.scale_y), 1.0)
    img = clip.source.image_at(local, pixel_scale)
    per_native = img.width() / nw
    k = per_native / max(1e-6, clip.scale)            # picture px per canvas px
    looks = [e for e in clip.effects if e.enabled and e.info().category == 'Look']
    if total.blur > 0.3:
        looks = looks + [EffectInstance('blur', True, {'amount': total.blur})]
    pad = 0.0
    if looks:
        img, pad = LOOK_CACHE.get(img, looks, k)
    pn = pad / per_native
    draw_rect = QRectF(-nw / 2 - pn, -nh / 2 - pn, nw + 2 * pn, nh + 2 * pn)

    p.save()
    p.setOpacity(opacity)
    p.translate((clip.x * cw + total.dx) * f, (clip.y * ch + total.dy) * f)
    p.rotate(clip.rotation + total.rotation)
    p.scale(clip.scale * f * total.scale_x, clip.scale * f * total.scale_y)
    if swing_rot:
        p.translate(0, -nh / 2)
        p.rotate(swing_rot)
        p.translate(0, nh / 2)
    if total.clip_fraction < 1.0 and total.clip_from:
        p.setClipRect(_clip_rect(nw + 2 * pn, nh + 2 * pn, total.clip_fraction, total.clip_from))
    p.drawImage(draw_rect, img)
    p.restore()


def render_timeline(tl: Timeline, t: float, out_width: int | None = None) -> QImage:
    out_w = out_width or tl.width
    f = out_w / tl.width
    out_h = max(1, int(round(tl.height * f)))
    frame = QImage(out_w, out_h, QImage.Format.Format_ARGB32_Premultiplied)
    frame.fill(Qt.GlobalColor.transparent)
    p = QPainter(frame)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
    for clip in tl.active(t):
        draw_clip(p, clip, t - clip.start, tl.width, tl.height, f)
    p.end()
    return frame


def clip_bounds(clip: Clip, local: float, cw: int, ch: int) -> QRectF:
    """Approximate on-canvas box of a clip at a moment (canvas pixels), for selection."""
    move, motion, _ = clip.motion_at(local, cw, ch)
    t = move.combine(motion)
    w, h = clip.size()
    w, h = w * abs(t.scale_x), h * abs(t.scale_y)
    a = math.radians(clip.rotation + t.rotation)
    bw = abs(w * math.cos(a)) + abs(h * math.sin(a))
    bh = abs(w * math.sin(a)) + abs(h * math.cos(a))
    cx, cy = clip.x * cw + t.dx, clip.y * ch + t.dy
    return QRectF(cx - bw / 2, cy - bh / 2, bw, bh)


def snapshot(tl: Timeline) -> dict:
    return copy.deepcopy(tl.to_dict())

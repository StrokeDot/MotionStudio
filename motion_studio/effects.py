"""Animation maths: easing curves, directions and the In / Loop / Out effects.

Everything here is pure Python with no Qt, so it is easy to test. An effect
turns a phase's settings and a progress value into a Transform: how far the
object is moved, scaled, turned, faded, blurred or clipped at that moment.

Direction always means the direction the object MOVES:
  * In  "up"  -> it starts below its place and travels up into it.
  * Out "up"  -> it leaves its place travelling up.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

# ---------------------------------------------------------------- directions

DIRECTIONS = {
    'up': (0.0, -1.0),
    'down': (0.0, 1.0),
    'left': (-1.0, 0.0),
    'right': (1.0, 0.0),
    'up-left': (-math.sqrt(0.5), -math.sqrt(0.5)),
    'up-right': (math.sqrt(0.5), -math.sqrt(0.5)),
    'down-left': (-math.sqrt(0.5), math.sqrt(0.5)),
    'down-right': (math.sqrt(0.5), math.sqrt(0.5)),
}
OPPOSITE = {'up': 'down', 'down': 'up', 'left': 'right', 'right': 'left',
            'up-left': 'down-right', 'down-right': 'up-left',
            'up-right': 'down-left', 'down-left': 'up-right'}

# ---------------------------------------------------------------- easing


def _clamp(p: float) -> float:
    return 0.0 if p < 0 else 1.0 if p > 1 else p


def _back_out(p: float, s: float = 1.70158) -> float:
    p -= 1
    return p * p * ((s + 1) * p + s) + 1


def _bounce_out(p: float) -> float:
    n, d = 7.5625, 2.75
    if p < 1 / d:
        return n * p * p
    if p < 2 / d:
        p -= 1.5 / d
        return n * p * p + 0.75
    if p < 2.5 / d:
        p -= 2.25 / d
        return n * p * p + 0.9375
    p -= 2.625 / d
    return n * p * p + 0.984375


EASINGS = {
    'Linear': lambda p: p,
    'Ease in': lambda p: p ** 3,
    'Ease out': lambda p: 1 - (1 - p) ** 3,
    'Ease in-out': lambda p: 4 * p ** 3 if p < 0.5 else 1 - (-2 * p + 2) ** 3 / 2,
    'Smooth (sine)': lambda p: -(math.cos(math.pi * p) - 1) / 2,
    'Strong out': lambda p: 1 - (1 - p) ** 5,
    'Overshoot': _back_out,
}


def ease(name: str, p: float) -> float:
    return EASINGS.get(name, EASINGS['Ease out'])(_clamp(p))


def bounce_curve(p: float, bounces: int) -> float:
    """0 -> 1 arriving like a dropped ball: hits the target, hops back, settles.

    `bounces` (1-6) sets how many hops follow the first hit.
    """
    p = _clamp(p)
    if bounces <= 0:
        return 1 - (1 - p) ** 2
    if bounces == 3:
        return _bounce_out(p)
    # General version: first fall takes a share of the time, then hops whose
    # height and length shrink geometrically (restitution r).
    r = 0.5
    lengths = [1.0] + [2 * (r ** (k / 2)) for k in range(1, bounces + 1)]
    total = sum(lengths)
    t = p * total
    if t <= lengths[0]:
        x = t / lengths[0]
        return x * x
    t -= lengths[0]
    for k in range(1, bounces + 1):
        seg = lengths[k]
        if t <= seg:
            x = (t / seg) * 2 - 1          # -1 .. 1 across the hop
            height = r ** k
            return 1 - height * (1 - x * x)
        t -= seg
    return 1.0


def spring_curve(p: float, bounces: int) -> float:
    """0 -> 1 like a soft spring: passes the target, swings back, settles.

    This is the "slow bounce": smooth, with overshoot on both sides.
    """
    p = _clamp(p)
    if p >= 1:
        return 1.0
    n = max(1, bounces)
    omega = math.pi * (n + 0.5)
    decay = 3.0 + 1.2 * n
    value = 1 - math.exp(-decay * p) * math.cos(omega * p)
    # Make sure the end lands exactly on the target.
    end = 1 - math.exp(-decay) * math.cos(omega)
    return value + (1 - end) * p


# ---------------------------------------------------------------- transform


@dataclass
class Transform:
    dx: float = 0.0          # pixels in canvas space
    dy: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0
    rotation: float = 0.0    # degrees, clockwise
    opacity: float = 1.0
    blur: float = 0.0        # pixels
    # Wipe: visible fraction (0..1) of the object, revealed from `clip_from`.
    clip_fraction: float = 1.0
    clip_from: str = ''

    def combine(self, other: 'Transform') -> 'Transform':
        frac, side = self.clip_fraction, self.clip_from
        if other.clip_fraction < frac:
            frac, side = other.clip_fraction, other.clip_from
        return Transform(
            dx=self.dx + other.dx, dy=self.dy + other.dy,
            scale_x=self.scale_x * other.scale_x, scale_y=self.scale_y * other.scale_y,
            rotation=self.rotation + other.rotation,
            opacity=self.opacity * other.opacity,
            blur=max(self.blur, other.blur),
            clip_fraction=frac, clip_from=side)


# ---------------------------------------------------------------- phases


@dataclass
class Phase:
    effect: str = 'None'
    direction: str = 'up'
    duration: float = 1.0       # seconds (In / Out); for Loop: seconds per cycle
    easing: str = 'Ease out'
    distance: float = 100.0     # % : 100 = starts just off-screen (Slide / Bounce)
    amount: float = 100.0       # % strength for zoom, spin, blur, loop size
    bounces: int = 3
    fade: bool = True           # also fade while moving

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d: dict) -> 'Phase':
        p = cls()
        for k, v in (d or {}).items():
            if hasattr(p, k):
                setattr(p, k, type(getattr(p, k))(v))
        return p


@dataclass
class EffectInfo:
    name: str
    direction: bool = False
    easing: bool = False
    distance: bool = False
    amount: bool = False
    bounces: bool = False
    fade: bool = False
    hint: str = ''


IN_OUT_EFFECTS = [
    EffectInfo('None'),
    EffectInfo('Fade', easing=True, hint='Fades in or out in place.'),
    EffectInfo('Slide', direction=True, easing=True, distance=True, fade=True,
               hint='Travels in a straight line.'),
    EffectInfo('Bounce', direction=True, distance=True, bounces=True, fade=True,
               hint='Lands like a dropped ball: hits its spot and hops back.'),
    EffectInfo('Slow bounce', direction=True, distance=True, bounces=True, fade=True,
               hint='Soft spring: passes its spot, swings back and settles.'),
    EffectInfo('Pop', amount=True, bounces=False, fade=True,
               hint='Grows from nothing with a small overshoot.'),
    EffectInfo('Zoom', easing=True, amount=True, fade=True,
               hint='Shrinks from large down to its size.'),
    EffectInfo('Spin', direction=True, easing=True, amount=True, fade=True,
               hint='Turns while growing. Left/right picks the turning way.'),
    EffectInfo('Flip', direction=True, easing=True, fade=True,
               hint='Flips like a card. Up/down flips vertically.'),
    EffectInfo('Wipe', direction=True, easing=True,
               hint='Revealed by an edge moving across it.'),
    EffectInfo('Blur', easing=True, amount=True, fade=True,
               hint='Comes into focus from a blur.'),
    EffectInfo('Squash drop', direction=True, distance=True, bounces=True,
               hint='Bounce with squash and stretch on each landing.'),
]

LOOP_EFFECTS = [
    EffectInfo('None'),
    EffectInfo('Float', direction=True, amount=True, hint='Drifts gently back and forth.'),
    EffectInfo('Hop', direction=True, amount=True, hint='Keeps hopping in a direction.'),
    EffectInfo('Pulse', amount=True, hint='Grows and shrinks like a heartbeat.'),
    EffectInfo('Wiggle', amount=True, hint='Tilts left and right.'),
    EffectInfo('Swing', amount=True, hint='Swings like a hanging sign.'),
    EffectInfo('Spin', direction=True, hint='Turns round continuously.'),
    EffectInfo('Shake', amount=True, hint='Quick small shakes.'),
    EffectInfo('Blink', amount=True, hint='Fades down and up.'),
]

IN_OUT_BY_NAME = {e.name: e for e in IN_OUT_EFFECTS}
LOOP_BY_NAME = {e.name: e for e in LOOP_EFFECTS}


def _turn_sign(direction: str) -> float:
    return -1.0 if 'left' in direction or direction == 'up' else 1.0


def entrance(phase: Phase, p: float, travel: float) -> Transform:
    """Transform for an In effect at progress p (0 = start, 1 = at rest).

    `travel` is the distance in pixels that takes the object just off-screen
    in the phase's direction (computed by the renderer).
    """
    p = _clamp(p)
    name = phase.effect
    vx, vy = DIRECTIONS.get(phase.direction, (0.0, -1.0))
    dist = travel * phase.distance / 100.0
    amt = phase.amount / 100.0
    t = Transform()
    if name == 'None' or p >= 1:
        return t
    if name == 'Fade':
        t.opacity = ease(phase.easing, p)
        return t
    if name in ('Slide', 'Bounce', 'Slow bounce', 'Squash drop'):
        if name == 'Slide':
            k = ease(phase.easing, p)
        elif name == 'Slow bounce':
            k = spring_curve(p, phase.bounces)
        else:
            k = bounce_curve(p, phase.bounces)
        remaining = 1 - k
        # Object starts behind its place (opposite the travel direction).
        t.dx, t.dy = -vx * dist * remaining, -vy * dist * remaining
        if name == 'Squash drop':
            t.scale_x, t.scale_y = _squash(p, phase.bounces, vx, vy)
        if phase.fade:
            t.opacity = _clamp(p * 4)
        return t
    if name == 'Pop':
        s = _back_out(p, 1.70158 * max(0.2, amt))
        t.scale_x = t.scale_y = max(0.0, s)
        if phase.fade:
            t.opacity = _clamp(p * 3)
        return t
    if name == 'Zoom':
        k = ease(phase.easing, p)
        start = 1 + 2 * amt
        t.scale_x = t.scale_y = start + (1 - start) * k
        if phase.fade:
            t.opacity = k
        return t
    if name == 'Spin':
        k = ease(phase.easing, p)
        t.rotation = _turn_sign(phase.direction) * -360 * max(0.25, amt * 1.0) * (1 - k)
        t.scale_x = t.scale_y = k
        if phase.fade:
            t.opacity = k
        return t
    if name == 'Flip':
        k = ease(phase.easing, p)
        if phase.direction in ('up', 'down'):
            t.scale_y = k
        else:
            t.scale_x = k
        if phase.fade:
            t.opacity = _clamp(k * 2)
        return t
    if name == 'Wipe':
        t.clip_fraction = ease(phase.easing, p)
        t.clip_from = OPPOSITE.get(phase.direction, 'down')   # edge it starts from
        return t
    if name == 'Blur':
        k = ease(phase.easing, p)
        t.blur = 30 * amt * (1 - k)
        if phase.fade:
            t.opacity = k
        return t
    return t


def _squash(p: float, bounces: int, vx: float, vy: float) -> tuple[float, float]:
    """Squash along the travel axis near each landing, stretch while falling."""
    k = bounce_curve(p, bounces)
    near = 1 - min(1.0, abs(1 - k) * 12)          # 1 at touch-down
    speed = abs(bounce_curve(min(1, p + 0.01), bounces) - k) * 40
    along = 1 - 0.25 * near + 0.15 * min(1.0, speed)
    across = 1 / max(0.5, along)
    if abs(vy) >= abs(vx):
        return across, along
    return along, across


def exit_(phase: Phase, p: float, travel: float) -> Transform:
    """Out effect: the In effect with the opposite direction, played backwards."""
    # Works for every effect, including Wipe: an Out wipe moving right hides the
    # left side first, so the part still visible stays anchored on the right.
    mirrored = Phase(**{**phase.to_dict(), 'direction': OPPOSITE.get(phase.direction, phase.direction)})
    return entrance(mirrored, 1 - _clamp(p), travel)


def loop(phase: Phase, seconds: float, size: float) -> Transform:
    """Loop effect at time `seconds`; `size` is the object's size in pixels."""
    t = Transform()
    name = phase.effect
    if name == 'None':
        return t
    period = max(0.05, phase.duration)
    w = 2 * math.pi * seconds / period
    amt = phase.amount / 100.0
    vx, vy = DIRECTIONS.get(phase.direction, (0.0, -1.0))
    if name == 'Float':
        d = math.sin(w) * size * 0.08 * amt
        t.dx, t.dy = vx * d, vy * d
    elif name == 'Hop':
        d = abs(math.sin(w / 2)) * size * 0.15 * amt
        t.dx, t.dy = vx * d, vy * d
    elif name == 'Pulse':
        s = 1 + 0.08 * amt * (0.5 - 0.5 * math.cos(w))
        t.scale_x = t.scale_y = s
    elif name == 'Wiggle':
        t.rotation = math.sin(w) * 10 * amt
    elif name == 'Swing':
        t.rotation = math.sin(w) * 15 * amt
    elif name == 'Spin':
        t.rotation = _turn_sign(phase.direction) * 360 * (seconds / period)
    elif name == 'Shake':
        t.dx = math.sin(w * 3.0) * size * 0.02 * amt
        t.dy = math.sin(w * 4.3 + 1.0) * size * 0.015 * amt
    elif name == 'Blink':
        t.opacity = 1 - 0.8 * amt * (0.5 - 0.5 * math.cos(w))
    return t


def swing_pivot(phase: Phase) -> bool:
    """Swing turns around the object's top edge instead of its centre."""
    return phase.effect == 'Swing'


@dataclass
class Animation:
    """The three phases of one object's animation."""
    in_: Phase = field(default_factory=lambda: Phase(effect='Slow bounce', direction='up', duration=1.2))
    loop: Phase = field(default_factory=lambda: Phase(effect='None', duration=2.0, amount=100))
    out: Phase = field(default_factory=lambda: Phase(effect='None', direction='up', duration=1.0))

    def to_dict(self) -> dict:
        return {'in': self.in_.to_dict(), 'loop': self.loop.to_dict(), 'out': self.out.to_dict()}

    @classmethod
    def from_dict(cls, d: dict) -> 'Animation':
        return cls(Phase.from_dict(d.get('in')), Phase.from_dict(d.get('loop')),
                   Phase.from_dict(d.get('out')))

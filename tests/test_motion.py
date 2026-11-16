"""Checks every effect, direction and the transparent export."""
import json
import os
import subprocess
import sys

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile  # noqa: E402
os.environ.setdefault('XDG_DATA_HOME', tempfile.mkdtemp())   # keep tests out of the real app folder
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from PySide6.QtGui import QGuiApplication, QImage  # noqa: E402

APP = QGuiApplication.instance() or QGuiApplication([])

from motion_studio.effects import (DIRECTIONS, IN_OUT_EFFECTS, LOOP_EFFECTS, Phase,  # noqa: E402
                                   bounce_curve, entrance, exit_, spring_curve)
from motion_studio.document import Document  # noqa: E402
from motion_studio.export import export, find_ffmpeg  # noqa: E402
from motion_studio.library import catalogue, thumbnail_frames  # noqa: E402
from motion_studio.scene import ObjectSource  # noqa: E402
from motion_studio.timeline import EFFECT_TYPES, Clip, EffectInstance, Timeline, render_timeline  # noqa: E402

TRAVEL = 1000.0


@pytest.mark.parametrize('name', [e.name for e in IN_OUT_EFFECTS])
@pytest.mark.parametrize('direction', list(DIRECTIONS))
def test_in_ends_at_rest_and_out_starts_at_rest(name, direction):
    ph = Phase(effect=name, direction=direction)
    for t in (entrance(ph, 1.0, TRAVEL), exit_(ph, 0.0, TRAVEL)):
        assert abs(t.dx) < 1e-6 and abs(t.dy) < 1e-6
        assert t.scale_x == pytest.approx(1) and t.scale_y == pytest.approx(1)
        assert t.opacity == pytest.approx(1) and t.rotation == pytest.approx(0, abs=1e-6)
        assert t.blur == pytest.approx(0) and t.clip_fraction == pytest.approx(1)


@pytest.mark.parametrize('name', ['Slide', 'Bounce', 'Slow bounce', 'Squash drop'])
@pytest.mark.parametrize('direction', list(DIRECTIONS))
def test_moving_effects_follow_the_chosen_direction(name, direction):
    vx, vy = DIRECTIONS[direction]
    start = entrance(Phase(effect=name, direction=direction), 0.0, TRAVEL)
    # In: starts behind its place, i.e. opposite the travel direction, a full trip away.
    assert start.dx * vx + start.dy * vy == pytest.approx(-TRAVEL, rel=1e-3)
    end = exit_(Phase(effect=name, direction=direction), 1.0, TRAVEL)
    # Out: ends a full trip away along the travel direction.
    assert end.dx * vx + end.dy * vy == pytest.approx(TRAVEL, rel=1e-3)


@pytest.mark.parametrize('n', range(1, 7))
def test_curves_start_at_0_end_at_1(n):
    for f in (bounce_curve, spring_curve):
        assert f(0, n) == pytest.approx(0, abs=1e-6)
        assert f(1, n) == pytest.approx(1)


def test_slow_bounce_overshoots_and_bounce_does_not():
    spring = [spring_curve(i / 200, 2) for i in range(201)]
    ball = [bounce_curve(i / 200, 3) for i in range(201)]
    assert max(spring) > 1.02
    assert max(ball) <= 1.0 + 1e-9


def _alpha_at(img: QImage, x: int, y: int) -> int:
    return img.pixelColor(x, y).alpha()


def _star_clip(**kw):
    src = ObjectSource(kind='svg', path='builtin:star')
    src.load()
    c = Clip(source=src, **kw)
    c.fit(640, 360, 0.4)
    return c


def test_object_off_screen_at_start_of_slide_in():
    tl = Timeline(width=640, height=360)
    c = _star_clip(duration=2)
    c.trans_in = Phase(effect='Slide', direction='up', duration=1, fade=False)
    c.effects = [EffectInstance('shadow'), EffectInstance('glow')]
    tl.clips = [c]
    first = render_timeline(tl, 0.0)
    assert all(_alpha_at(first, x, y) == 0 for x in range(0, 640, 8) for y in range(0, 360, 8))
    rest = render_timeline(tl, 1.5)
    assert _alpha_at(rest, 320, 180) > 0


@pytest.mark.parametrize('etype', [e.id for e in EFFECT_TYPES])
def test_every_effect_renders(etype):
    tl = Timeline(width=320, height=180)
    c = _star_clip(duration=2)
    c.effects = [EffectInstance(etype)]
    tl.clips = [c]
    for t in (0.0, 0.3, 1.7):
        img = render_timeline(tl, t)
        assert any(_alpha_at(img, x, y) for x in range(0, 320, 4) for y in range(0, 180, 4))


def test_tracks_stack_and_hidden_tracks_are_skipped():
    tl = Timeline(width=320, height=180)
    a, b = _star_clip(duration=2, track=0), _star_clip(duration=2, track=1)
    tl.clips = [b, a]
    assert [c.track for c in tl.active(0.5)] == [0, 1]
    tl.hidden_tracks = {1}
    assert [c.track for c in tl.active(0.5)] == [0]
    assert tl.active(2.5) == []


def test_save_load_round_trip():
    tl = Timeline()
    c = _star_clip(start=1.0, duration=3, track=2)
    c.trans_in = Phase(effect='Bounce', direction='left', bounces=4)
    c.effects = [EffectInstance('glow', params={'size': 40})]
    tl.clips = [c, Clip(source=ObjectSource(kind='text'))]
    tl2 = Timeline.from_dict(json.loads(json.dumps(tl.to_dict())))
    assert tl2.to_dict()['clips'][0] == tl.to_dict()['clips'][0]
    assert tl2.clips[0].trans_in.direction == 'left' and tl2.clips[0].effects[0].params['size'] == 40


def test_document_undo_redo_split():
    doc = Document()
    src = ObjectSource(kind='svg', path='builtin:heart')
    src.load()
    clip = doc.add_sticker(src, start=0, duration=4)
    doc.add_effect(clip, 'pulse')
    doc.set_time(1.5)
    assert doc.split_selected()
    assert len(doc.timeline.clips) == 2
    assert sorted(round(c.duration, 3) for c in doc.timeline.clips) == [1.5, 2.5]
    doc.undo()
    assert len(doc.timeline.clips) == 1 and doc.timeline.clips[0].effects
    doc.undo()
    assert not doc.timeline.clips[0].effects
    doc.redo()
    doc.redo()
    assert len(doc.timeline.clips) == 2


def test_library_thumbnails_build_for_every_item():
    for kind in ('transitions', 'effects', 'stickers'):
        cats, items = catalogue(kind)
        assert cats
        for it in items:
            assert thumbnail_frames(it, 3)


def test_prores_export_keeps_transparency(tmp_path):
    tl = Timeline(width=640, height=360, fps=10)
    tl.clips = [_star_clip(duration=1.0)]
    out = str(tmp_path / 'clip.mov')
    export(tl, out)
    ff = find_ffmpeg()
    probe = subprocess.run([ff, '-hide_banner', '-i', out], capture_output=True, text=True).stderr
    assert 'prores' in probe and 'yuva444p' in probe
    png = str(tmp_path / 'alpha.png')
    subprocess.run([ff, '-v', 'error', '-y', '-ss', '0.9', '-i', out, '-vf', 'alphaextract',
                    '-frames:v', '1', png], check=True)
    a = QImage(png)
    assert a.pixelColor(2, 2).red() == 0                                     # background transparent
    assert max(a.pixelColor(x, 180).red() for x in range(260, 380)) > 200   # sticker opaque


def test_png_sequence(tmp_path):
    tl = Timeline(width=320, height=180, fps=5)
    tl.clips = [_star_clip(duration=1.0)]
    export(tl, str(tmp_path / 'frames'), 'png')
    assert len(os.listdir(tmp_path / 'frames')) == 5

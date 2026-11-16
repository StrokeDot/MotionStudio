"""Checks every effect, direction and the transparent export."""
import os
import subprocess
import sys

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from PySide6.QtGui import QGuiApplication, QImage  # noqa: E402

APP = QGuiApplication.instance() or QGuiApplication([])

from motion_studio.effects import (DIRECTIONS, IN_OUT_EFFECTS, LOOP_EFFECTS, Phase,  # noqa: E402
                                   bounce_curve, entrance, exit_, spring_curve)
from motion_studio.export import export, find_ffmpeg  # noqa: E402
from motion_studio.scene import Project, render_frame  # noqa: E402

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


def test_object_off_screen_at_start_of_slide_in():
    pr = Project(duration=2)
    pr.fit_object(0.3)
    pr.animation.in_ = Phase(effect='Slide', direction='up', duration=1, fade=False)
    first = render_frame(pr, 0.0, 480)
    assert all(_alpha_at(first, x, y) == 0 for x in range(0, 480, 8) for y in range(0, 270, 8))
    rest = render_frame(pr, 1.5, 480)
    assert _alpha_at(rest, 240, 135) > 0 or any(
        _alpha_at(rest, x, 135) > 0 for x in range(200, 280))


@pytest.mark.parametrize('loop_name', [e.name for e in LOOP_EFFECTS])
def test_every_loop_effect_renders(loop_name):
    pr = Project(duration=2)
    pr.animation.loop = Phase(effect=loop_name, duration=1.0)
    for t in (0.0, 0.3, 1.7):
        render_frame(pr, t, 320)


def test_prores_export_keeps_transparency(tmp_path):
    pr = Project(width=640, height=360, fps=10, duration=1.0)
    pr.fit_object(0.4)
    out = str(tmp_path / 'clip.mov')
    export(pr, out)
    ff = find_ffmpeg()
    probe = subprocess.run([ff, '-hide_banner', '-i', out], capture_output=True, text=True).stderr
    assert 'prores' in probe and 'yuva444p' in probe
    png = str(tmp_path / 'alpha.png')
    subprocess.run([ff, '-v', 'error', '-y', '-ss', '0.9', '-i', out, '-vf', 'alphaextract',
                    '-frames:v', '1', png], check=True)
    a = QImage(png)
    assert a.pixelColor(2, 2).red() == 0                 # background transparent
    assert max(a.pixelColor(x, 180).red() for x in range(200, 440)) > 200   # object opaque


def test_png_sequence(tmp_path):
    pr = Project(width=320, height=180, fps=5, duration=1.0)
    export(pr, str(tmp_path / 'frames'), 'png')
    assert len(os.listdir(tmp_path / 'frames')) == 5

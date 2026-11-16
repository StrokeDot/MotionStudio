"""The desktop window: object on the left, preview in the middle, effects on the right."""
from __future__ import annotations

import json
import os
import sys
import time

from PySide6.QtCore import QObject, QPointF, QRectF, QStandardPaths, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QImage, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QColorDialog, QComboBox,
                               QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFontComboBox,
                               QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel,
                               QMainWindow, QMessageBox, QPlainTextEdit, QProgressDialog, QPushButton,
                               QRadioButton, QScrollArea, QSlider, QSpinBox, QTabWidget, QToolButton,
                               QVBoxLayout, QWidget)

from . import __version__
from .effects import IN_OUT_BY_NAME, IN_OUT_EFFECTS, LOOP_BY_NAME, LOOP_EFFECTS, EASINGS, Phase
from .export import FORMATS, Cancelled, export
from .scene import ObjectSource, Project, render_frame

APP_NAME = 'Motion Studio'

ARROWS = {'up-left': '↖', 'up': '↑', 'up-right': '↗', 'left': '←', 'right': '→',
          'down-left': '↙', 'down': '↓', 'down-right': '↘'}
GRID = [['up-left', 'up', 'up-right'], ['left', None, 'right'], ['down-left', 'down', 'down-right']]


def data_dir() -> str:
    d = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    os.makedirs(d, exist_ok=True)
    return d


# ---------------------------------------------------------------- preview


class PreviewCanvas(QWidget):
    """Shows the current frame over a checkerboard (or a background picture you
    choose for comparison). Drag the object to move it."""

    moved = Signal()

    def __init__(self, window: 'MainWindow'):
        super().__init__()
        self.win = window
        self.frame: QImage | None = None
        self.background = 'checker'
        self.bg_image: QImage | None = None
        self._drag = None
        self.setMinimumSize(480, 270)
        self.setMouseTracking(True)

    def canvas_rect(self) -> QRectF:
        pr = self.win.project
        w, h = self.width() - 16, self.height() - 16
        k = min(w / pr.width, h / pr.height)
        cw, ch = pr.width * k, pr.height * k
        return QRectF((self.width() - cw) / 2, (self.height() - ch) / 2, cw, ch)

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor('#1b1d22'))
        r = self.canvas_rect()
        if self.background == 'checker':
            s = 12
            p.save()
            p.setClipRect(r)
            for yi in range(int(r.height() / s) + 1):
                for xi in range(int(r.width() / s) + 1):
                    p.fillRect(QRectF(r.left() + xi * s, r.top() + yi * s, s, s),
                               QColor('#bdbdbd') if (xi + yi) % 2 else QColor('#e8e8e8'))
            p.restore()
        elif self.background == 'image' and self.bg_image is not None:
            p.drawImage(r, self.bg_image)
        else:
            p.fillRect(r, QColor(self.background))
        if self.frame is not None:
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawImage(r, self.frame)
        p.setPen(QPen(QColor('#5a5f6b'), 1))
        p.drawRect(r)

    def _to_canvas(self, pos) -> tuple[float, float]:
        r = self.canvas_rect()
        return (pos.x() - r.left()) / r.width(), (pos.y() - r.top()) / r.height()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            pr = self.win.project
            self._drag = (self._to_canvas(e.position()), (pr.x, pr.y))

    def mouseMoveEvent(self, e):
        if self._drag:
            (sx, sy), (ox, oy) = self._drag
            x, y = self._to_canvas(e.position())
            self.win.project.x = min(1.5, max(-0.5, ox + x - sx))
            self.win.project.y = min(1.5, max(-0.5, oy + y - sy))
            self.moved.emit()

    def mouseReleaseEvent(self, _):
        self._drag = None


class PhaseBar(QWidget):
    """A strip under the slider showing where In, Loop and Out happen."""

    def __init__(self, window: 'MainWindow'):
        super().__init__()
        self.win = window
        self.setFixedHeight(14)

    def paintEvent(self, _):
        pr = self.win.project
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor('#2a2d34'))
        d = max(1e-6, pr.duration)
        ie, os_ = pr.in_end(), pr.out_start()
        if pr.animation.loop.effect != 'None':
            p.fillRect(QRectF(0, 4, w, h - 8), QColor('#3d6e5a'))
        if ie > 0:
            p.fillRect(QRectF(0, 0, w * ie / d, h), QColor('#3a7bd5'))
        if os_ < d:
            p.fillRect(QRectF(w * os_ / d, 0, w * (d - os_) / d, h), QColor('#d5763a'))
        x = w * self.win.time / d
        p.setPen(QPen(QColor('white'), 2))
        p.drawLine(int(x), 0, int(x), h)


# ---------------------------------------------------------------- effect editor


class PhaseEditor(QWidget):
    changed = Signal()
    preview = Signal()

    def __init__(self, kind: str, window: 'MainWindow'):
        super().__init__()
        self.kind = kind                    # 'in', 'loop', 'out'
        self.win = window
        self._loading = False
        effects = LOOP_EFFECTS if kind == 'loop' else IN_OUT_EFFECTS
        self.infos = LOOP_BY_NAME if kind == 'loop' else IN_OUT_BY_NAME

        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.effect = QComboBox()
        self.effect.addItems([e.name for e in effects])
        form.addRow('Effect', self.effect)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet('color:#9aa3b2;')
        form.addRow('', self.hint)

        # Direction picker: a 3x3 grid of arrows.
        self.dir_box = QWidget()
        grid = QGridLayout(self.dir_box)
        grid.setSpacing(2)
        grid.setContentsMargins(0, 0, 0, 0)
        self.dir_group = QButtonGroup(self)
        self.dir_buttons = {}
        for r, row in enumerate(GRID):
            for c, name in enumerate(row):
                if name is None:
                    continue
                b = QToolButton()
                b.setText(ARROWS[name])
                b.setCheckable(True)
                b.setFixedSize(34, 30)
                b.setToolTip(f'Moves {name.replace("-", " ")}')
                f = b.font()
                f.setPointSize(13)
                b.setFont(f)
                self.dir_group.addButton(b)
                self.dir_buttons[name] = b
                grid.addWidget(b, r, c)
        self.dir_label = QLabel('Moves')
        form.addRow(self.dir_label, self.dir_box)

        self.duration = QDoubleSpinBox()
        self.duration.setRange(0.05, 60)
        self.duration.setSingleStep(0.1)
        self.duration.setSuffix(' s')
        form.addRow('Cycle length' if kind == 'loop' else 'Duration', self.duration)

        self.easing = QComboBox()
        self.easing.addItems(list(EASINGS))
        self.easing_label = QLabel('Easing')
        form.addRow(self.easing_label, self.easing)

        self.distance = QSpinBox()
        self.distance.setRange(1, 400)
        self.distance.setSuffix(' %')
        self.distance.setToolTip('100 % = starts (or ends) just off-screen. Lower = shorter trip.')
        self.distance_label = QLabel('Distance')
        form.addRow(self.distance_label, self.distance)

        self.amount = QSpinBox()
        self.amount.setRange(1, 500)
        self.amount.setSuffix(' %')
        self.amount_label = QLabel('Strength')
        form.addRow(self.amount_label, self.amount)

        self.bounces = QSpinBox()
        self.bounces.setRange(1, 6)
        self.bounces_label = QLabel('Bounces')
        form.addRow(self.bounces_label, self.bounces)

        self.fade = QCheckBox('Fade while moving')
        form.addRow('', self.fade)
        lay.addLayout(form)

        self.play_btn = QPushButton('▶  Preview this effect')
        lay.addWidget(self.play_btn)

        # My effects (saved presets for this phase).
        box = QGroupBox('My effects')
        bl = QVBoxLayout(box)
        self.presets = QComboBox()
        bl.addWidget(self.presets)
        row = QHBoxLayout()
        self.apply_btn = QPushButton('Use')
        self.save_btn = QPushButton('Save current…')
        self.del_btn = QPushButton('Delete')
        for b in (self.apply_btn, self.save_btn, self.del_btn):
            row.addWidget(b)
        bl.addLayout(row)
        lay.addWidget(box)
        lay.addStretch(1)

        for w in (self.effect, self.easing):
            w.currentIndexChanged.connect(self._edited)
        for w in (self.duration, self.distance, self.amount, self.bounces):
            w.valueChanged.connect(self._edited)
        self.fade.toggled.connect(self._edited)
        self.dir_group.buttonClicked.connect(self._edited)
        self.play_btn.clicked.connect(self.preview)
        self.apply_btn.clicked.connect(self._use_preset)
        self.save_btn.clicked.connect(self._save_preset)
        self.del_btn.clicked.connect(self._delete_preset)
        self.refresh_presets()

    # ---- phase <-> widgets

    def phase(self) -> Phase:
        a = self.win.project.animation
        return {'in': a.in_, 'loop': a.loop, 'out': a.out}[self.kind]

    def load(self):
        self._loading = True
        ph = self.phase()
        self.effect.setCurrentText(ph.effect)
        if ph.direction in self.dir_buttons:
            self.dir_buttons[ph.direction].setChecked(True)
        self.duration.setValue(ph.duration)
        self.easing.setCurrentText(ph.easing)
        self.distance.setValue(int(ph.distance))
        self.amount.setValue(int(ph.amount))
        self.bounces.setValue(int(ph.bounces))
        self.fade.setChecked(ph.fade)
        self._loading = False
        self._update_visibility()

    def _edited(self, *_):
        if self._loading:
            return
        ph = self.phase()
        ph.effect = self.effect.currentText()
        for name, b in self.dir_buttons.items():
            if b.isChecked():
                ph.direction = name
        ph.duration = self.duration.value()
        ph.easing = self.easing.currentText()
        ph.distance = float(self.distance.value())
        ph.amount = float(self.amount.value())
        ph.bounces = self.bounces.value()
        ph.fade = self.fade.isChecked()
        self._update_visibility()
        self.changed.emit()

    def _update_visibility(self):
        info = self.infos.get(self.effect.currentText())
        self.hint.setText(info.hint if info else '')
        pairs = [(self.dir_label, self.dir_box, info.direction),
                 (self.easing_label, self.easing, info.easing),
                 (self.distance_label, self.distance, info.distance),
                 (self.amount_label, self.amount, info.amount),
                 (self.bounces_label, self.bounces, info.bounces),
                 (None, self.fade, info.fade)]
        for label, w, show in pairs:
            w.setVisible(show)
            if label:
                label.setVisible(show)
        # Spin only turns two ways.
        only_lr = self.effect.currentText() == 'Spin'
        for name, b in self.dir_buttons.items():
            b.setEnabled(not only_lr or name in ('left', 'right'))
        if only_lr and self.phase().direction not in ('left', 'right'):
            self.dir_buttons['right'].setChecked(True)
            self.phase().direction = 'right'
        self.dir_label.setText('Turns' if only_lr else 'Moves')
        self.play_btn.setEnabled(self.effect.currentText() != 'None')

    # ---- presets

    def _preset_file(self) -> str:
        return os.path.join(data_dir(), 'my_effects.json')

    def _read_presets(self) -> dict:
        try:
            with open(self._preset_file(), encoding='utf-8') as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _write_presets(self, data: dict):
        with open(self._preset_file(), 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

    def refresh_presets(self):
        names = sorted(self._read_presets().get(self.kind, {}))
        self.presets.clear()
        self.presets.addItems(names)
        has = bool(names)
        self.apply_btn.setEnabled(has)
        self.del_btn.setEnabled(has)

    def _use_preset(self):
        d = self._read_presets().get(self.kind, {}).get(self.presets.currentText())
        if not d:
            return
        new = Phase.from_dict(d)
        ph = self.phase()
        for k, v in new.to_dict().items():
            setattr(ph, k, v)
        self.load()
        self.changed.emit()

    def _save_preset(self):
        name, ok = QInputDialog.getText(self, 'Save effect', 'Name for this effect:',
                                        text=f'{self.phase().effect} {self.phase().direction}')
        if not ok or not name.strip():
            return
        data = self._read_presets()
        data.setdefault(self.kind, {})[name.strip()] = self.phase().to_dict()
        self._write_presets(data)
        self.refresh_presets()
        self.presets.setCurrentText(name.strip())

    def _delete_preset(self):
        name = self.presets.currentText()
        data = self._read_presets()
        if name in data.get(self.kind, {}):
            del data[self.kind][name]
            self._write_presets(data)
            self.refresh_presets()


# ---------------------------------------------------------------- export thread


class ExportWorker(QObject):
    progress = Signal(int, int)
    finished = Signal(str, str)      # path, error message ('' = ok)

    def __init__(self, project_dict: dict, path: str, fmt: str):
        super().__init__()
        self.project_dict, self.path, self.fmt = project_dict, path, fmt
        self.cancel = False

    def run(self):
        try:
            project = Project.from_dict(self.project_dict)

            def cb(done, total):
                self.progress.emit(done, total)
                return not self.cancel

            export(project, self.path, self.fmt, cb)
            self.finished.emit(self.path, '')
        except Cancelled:
            self.finished.emit(self.path, 'cancelled')
        except Exception as exc:    # shown to the user
            self.finished.emit(self.path, str(exc))


# ---------------------------------------------------------------- main window


CANVAS_PRESETS = [('1920 × 1080 (16:9)', 1920, 1080), ('3840 × 2160 (4K)', 3840, 2160),
                  ('1080 × 1920 (vertical)', 1080, 1920), ('1080 × 1080 (square)', 1080, 1080),
                  ('1280 × 720', 1280, 720)]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f'{APP_NAME} {__version__}')
        self.project = Project()
        self.project.fit_object(0.35)
        self.project_path = ''
        self.time = 0.0
        self.playing = False
        self.play_until: float | None = None
        self._last_tick = 0.0
        self._thread = None

        central = QWidget()
        cl = QVBoxLayout(central)
        self.canvas = PreviewCanvas(self)
        cl.addWidget(self.canvas, 1)
        self.phase_bar = PhaseBar(self)
        cl.addWidget(self.phase_bar)
        trow = QHBoxLayout()
        self.play_btn = QPushButton('▶')
        self.play_btn.setFixedWidth(44)
        self.loop_box = QCheckBox('Repeat')
        self.loop_box.setChecked(True)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.time_label = QLabel()
        self.time_label.setMinimumWidth(110)
        self.bg_combo = QComboBox()
        self.bg_combo.addItems(['Checkerboard', 'Black', 'White', 'Green', 'Background picture…'])
        self.bg_combo.setToolTip('Preview only. Never exported.')
        for w in (self.play_btn, self.loop_box, self.slider, self.time_label, QLabel('Behind:'), self.bg_combo):
            trow.addWidget(w, 1 if w is self.slider else 0)
        cl.addLayout(trow)
        self.setCentralWidget(central)

        self._build_left()
        self._build_right()
        self._build_menu()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.play_btn.clicked.connect(self.toggle_play)
        self.slider.valueChanged.connect(self._slider_moved)
        self.bg_combo.currentIndexChanged.connect(self._bg_changed)
        self.canvas.moved.connect(self._object_dragged)

        self.resize(1400, 820)
        self.load_project_into_ui()

    # ---- layout pieces

    def _build_left(self):
        panel = QWidget()
        lay = QVBoxLayout(panel)

        obj = QGroupBox('Object')
        ol = QVBoxLayout(obj)
        row = QHBoxLayout()
        self.load_btn = QPushButton('Picture / SVG / GIF…')
        self.text_btn = QPushButton('Text')
        row.addWidget(self.load_btn)
        row.addWidget(self.text_btn)
        ol.addLayout(row)
        self.obj_label = QLabel()
        self.obj_label.setWordWrap(True)
        self.obj_label.setStyleSheet('color:#9aa3b2;')
        ol.addWidget(self.obj_label)

        self.text_box = QGroupBox('Text')
        tf = QFormLayout(self.text_box)
        self.text_edit = QPlainTextEdit()
        self.text_edit.setFixedHeight(60)
        tf.addRow(self.text_edit)
        self.font_combo = QFontComboBox()
        tf.addRow('Font', self.font_combo)
        self.font_size = QSpinBox()
        self.font_size.setRange(8, 600)
        tf.addRow('Size', self.font_size)
        srow = QHBoxLayout()
        self.bold = QCheckBox('Bold')
        self.italic = QCheckBox('Italic')
        srow.addWidget(self.bold)
        srow.addWidget(self.italic)
        tf.addRow(srow)
        self.color_btn = QPushButton()
        self.outline_btn = QPushButton()
        tf.addRow('Colour', self.color_btn)
        tf.addRow('Outline', self.outline_btn)
        self.outline_w = QDoubleSpinBox()
        self.outline_w.setRange(0, 60)
        tf.addRow('Outline width', self.outline_w)
        ol.addWidget(self.text_box)
        lay.addWidget(obj)

        place = QGroupBox('Placement (its resting spot)')
        pf = QFormLayout(place)
        self.pos_x = QDoubleSpinBox()
        self.pos_y = QDoubleSpinBox()
        for s in (self.pos_x, self.pos_y):
            s.setRange(-50, 150)
            s.setSuffix(' %')
            s.setDecimals(1)
        self.size_s = QDoubleSpinBox()
        self.size_s.setRange(1, 2000)
        self.size_s.setSuffix(' %')
        self.rot_s = QDoubleSpinBox()
        self.rot_s.setRange(-360, 360)
        self.rot_s.setSuffix(' °')
        self.opa_s = QSpinBox()
        self.opa_s.setRange(0, 100)
        self.opa_s.setSuffix(' %')
        pf.addRow('Left → right', self.pos_x)
        pf.addRow('Top → bottom', self.pos_y)
        pf.addRow('Size', self.size_s)
        pf.addRow('Rotation', self.rot_s)
        pf.addRow('Opacity', self.opa_s)
        prow = QHBoxLayout()
        self.center_btn = QPushButton('Centre')
        self.fit_btn = QPushButton('Fit')
        prow.addWidget(self.center_btn)
        prow.addWidget(self.fit_btn)
        pf.addRow(prow)
        lay.addWidget(place)

        canvas_box = QGroupBox('Video')
        vf = QFormLayout(canvas_box)
        self.canvas_combo = QComboBox()
        self.canvas_combo.addItems([n for n, _, _ in CANVAS_PRESETS])
        self.fps_combo = QComboBox()
        self.fps_combo.addItems(['24', '25', '30', '50', '60'])
        self.dur_s = QDoubleSpinBox()
        self.dur_s.setRange(0.2, 120)
        self.dur_s.setSingleStep(0.5)
        self.dur_s.setSuffix(' s')
        vf.addRow('Size', self.canvas_combo)
        vf.addRow('Frames / s', self.fps_combo)
        vf.addRow('Length', self.dur_s)
        lay.addWidget(canvas_box)
        lay.addStretch(1)

        self.export_btn = QPushButton('Export…')
        self.export_btn.setStyleSheet('font-weight:bold; padding:8px;')
        lay.addWidget(self.export_btn)

        scroll = QScrollArea()
        scroll.setWidget(panel)
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(360)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        from PySide6.QtWidgets import QDockWidget
        dock = QDockWidget('Object', self)
        dock.setWidget(scroll)
        dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)

        self.load_btn.clicked.connect(self.choose_file)
        self.text_btn.clicked.connect(self.use_text)
        self.text_edit.textChanged.connect(self._text_changed)
        self.font_combo.currentFontChanged.connect(self._text_changed)
        self.font_size.valueChanged.connect(self._text_changed)
        self.bold.toggled.connect(self._text_changed)
        self.italic.toggled.connect(self._text_changed)
        self.outline_w.valueChanged.connect(self._text_changed)
        self.color_btn.clicked.connect(lambda: self._pick_color('color'))
        self.outline_btn.clicked.connect(lambda: self._pick_color('outline_color'))
        for s in (self.pos_x, self.pos_y, self.size_s, self.rot_s, self.opa_s):
            s.valueChanged.connect(self._placement_changed)
        self.center_btn.clicked.connect(self._center)
        self.fit_btn.clicked.connect(self._fit)
        self.canvas_combo.currentIndexChanged.connect(self._video_changed)
        self.fps_combo.currentIndexChanged.connect(self._video_changed)
        self.dur_s.valueChanged.connect(self._video_changed)
        self.export_btn.clicked.connect(self.export_dialog)

    def _build_right(self):
        from PySide6.QtWidgets import QDockWidget
        self.tabs = QTabWidget()
        self.editors = {}
        for kind, title in (('in', 'In'), ('loop', 'Loop'), ('out', 'Out')):
            ed = PhaseEditor(kind, self)
            ed.changed.connect(self._animation_changed)
            ed.preview.connect(lambda k=kind: self.preview_phase(k))
            self.editors[kind] = ed
            self.tabs.addTab(ed, title)
        dock = QDockWidget('Animation', self)
        dock.setWidget(self.tabs)
        dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        dock.setMinimumWidth(320)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

    def _build_menu(self):
        m = self.menuBar().addMenu('&File')
        for text, key, fn in (('New', QKeySequence.StandardKey.New, self.new_project),
                              ('Open project…', QKeySequence.StandardKey.Open, self.open_project),
                              ('Save project', QKeySequence.StandardKey.Save, self.save_project),
                              ('Save project as…', QKeySequence.StandardKey.SaveAs,
                               lambda: self.save_project(True)),
                              ('Export…', 'Ctrl+E', self.export_dialog)):
            a = QAction(text, self)
            a.setShortcut(key)
            a.triggered.connect(fn)
            m.addAction(a)
        sp = QAction('Play / pause', self)
        sp.setShortcut('Space')
        sp.triggered.connect(self.toggle_play)
        self.addAction(sp)

    # ---- syncing project <-> widgets

    def load_project_into_ui(self):
        pr = self.project
        self._syncing = True
        st = pr.source.text
        self.text_edit.setPlainText(st.text)
        self.font_combo.setCurrentFont(QFont(st.family))
        self.font_size.setValue(int(st.size))
        self.bold.setChecked(st.bold)
        self.italic.setChecked(st.italic)
        self.outline_w.setValue(st.outline_width)
        self._paint_color_buttons()
        self._sync_placement()
        idx = next((i for i, (_, w, h) in enumerate(CANVAS_PRESETS)
                    if (w, h) == (pr.width, pr.height)), 0)
        self.canvas_combo.setCurrentIndex(idx)
        self.fps_combo.setCurrentText(f'{pr.fps:g}')
        self.dur_s.setValue(pr.duration)
        self._syncing = False
        for ed in self.editors.values():
            ed.load()
        self._update_object_label()
        self._timing_changed()

    def _sync_placement(self):
        pr = self.project
        was = getattr(self, '_syncing', False)
        self._syncing = True
        self.pos_x.setValue(pr.x * 100)
        self.pos_y.setValue(pr.y * 100)
        self.size_s.setValue(pr.scale * 100)
        self.rot_s.setValue(pr.rotation)
        self.opa_s.setValue(int(round(pr.opacity * 100)))
        self._syncing = was

    def _paint_color_buttons(self):
        st = self.project.source.text
        for b, c in ((self.color_btn, st.color), (self.outline_btn, st.outline_color)):
            b.setText(c)
            b.setStyleSheet(f'background:{c}; color:{"#000" if QColor(c).lightness() > 128 else "#fff"};')

    def _update_object_label(self):
        src = self.project.source
        is_text = src.kind == 'text'
        self.text_box.setVisible(is_text)
        if is_text:
            self.obj_label.setText('Text object.')
        else:
            w, h = src.native_size()
            self.obj_label.setText(f'{os.path.basename(src.path)}  ({src.kind}, {int(w)}×{int(h)})')

    # ---- object

    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Choose a picture, SVG or animated GIF', '',
            'Pictures (*.png *.jpg *.jpeg *.webp *.svg *.gif *.bmp *.tif *.tiff);;All files (*)')
        if not path:
            return
        try:
            self.project.source = ObjectSource.from_file(path)
        except Exception as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            return
        self.project.fit_object(0.5)
        self._sync_placement()
        self._update_object_label()
        self.refresh()

    def use_text(self):
        if self.project.source.kind != 'text':
            old = self.project.source.text
            self.project.source = ObjectSource(kind='text', text=old)
            self.project.fit_object(0.35)
            self._sync_placement()
        self._update_object_label()
        self.refresh()

    def _text_changed(self, *_):
        if getattr(self, '_syncing', False):
            return
        st = self.project.source.text
        st.text = self.text_edit.toPlainText()
        st.family = self.font_combo.currentFont().family()
        st.size = float(self.font_size.value())
        st.bold = self.bold.isChecked()
        st.italic = self.italic.isChecked()
        st.outline_width = self.outline_w.value()
        self.refresh()

    def _pick_color(self, attr):
        st = self.project.source.text
        c = QColorDialog.getColor(QColor(getattr(st, attr)), self, 'Choose colour')
        if c.isValid():
            setattr(st, attr, c.name())
            self._paint_color_buttons()
            self.refresh()

    def _placement_changed(self, *_):
        if getattr(self, '_syncing', False):
            return
        pr = self.project
        pr.x, pr.y = self.pos_x.value() / 100, self.pos_y.value() / 100
        pr.scale = self.size_s.value() / 100
        pr.rotation = self.rot_s.value()
        pr.opacity = self.opa_s.value() / 100
        self.refresh()

    def _object_dragged(self):
        self._sync_placement()
        self.refresh()

    def _center(self):
        self.project.x = self.project.y = 0.5
        self._sync_placement()
        self.refresh()

    def _fit(self):
        self.project.fit_object(0.5)
        self._sync_placement()
        self.refresh()

    def _video_changed(self, *_):
        if getattr(self, '_syncing', False):
            return
        _, w, h = CANVAS_PRESETS[self.canvas_combo.currentIndex()]
        old_w = self.project.width
        self.project.width, self.project.height = w, h
        self.project.scale *= w / old_w if old_w else 1
        self.project.fps = float(self.fps_combo.currentText())
        self.project.duration = self.dur_s.value()
        self._sync_placement()
        self._timing_changed()

    def _animation_changed(self):
        self._timing_changed()

    def _timing_changed(self):
        pr = self.project
        self.slider.blockSignals(True)
        self.slider.setRange(0, pr.frame_count() - 1)
        self.time = min(self.time, pr.duration)
        self.slider.setValue(int(round(self.time * pr.fps)))
        self.slider.blockSignals(False)
        self.refresh()

    def _bg_changed(self, i):
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

    # ---- playback

    def refresh(self):
        pr = self.project
        width = max(64, min(pr.width, int(self.canvas.canvas_rect().width() * self.devicePixelRatioF())))
        try:
            self.canvas.frame = render_frame(pr, self.time, width)
        except Exception as exc:   # keep the window alive if a frame fails
            self.statusBar().showMessage(f'Could not draw this frame: {exc}', 5000)
        self.time_label.setText(f'{self.time:5.2f} / {pr.duration:.2f} s')
        self.canvas.update()
        self.phase_bar.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, self.refresh)

    def _slider_moved(self, v):
        self.time = v / self.project.fps
        self.refresh()

    def toggle_play(self):
        if self.playing:
            self.stop()
        else:
            if self.time >= self.project.duration - 1e-6:
                self.time = 0.0
            self.play_until = None
            self.start()

    def start(self):
        self.playing = True
        self.play_btn.setText('❚❚')
        self._last_tick = time.perf_counter()
        self.timer.start(max(5, int(1000 / self.project.fps)))

    def stop(self):
        self.playing = False
        self.play_btn.setText('▶')
        self.timer.stop()

    def preview_phase(self, kind):
        pr = self.project
        if kind == 'in':
            self.time, self.play_until = 0.0, pr.in_end() + 0.4
        elif kind == 'out':
            self.time, self.play_until = max(0.0, pr.out_start() - 0.4), pr.duration
        else:
            self.time, self.play_until = pr.in_end(), pr.out_start()
        self.start()

    def _tick(self):
        now = time.perf_counter()
        self.time += now - self._last_tick
        self._last_tick = now
        end = self.play_until if self.play_until is not None else self.project.duration
        if self.time >= end:
            if self.play_until is None and self.loop_box.isChecked():
                self.time = 0.0
            else:
                self.time = min(end, self.project.duration)
                self.stop()
        self.slider.blockSignals(True)
        self.slider.setValue(int(self.time * self.project.fps))
        self.slider.blockSignals(False)
        self.refresh()

    # ---- files

    def new_project(self):
        self.stop()
        self.project = Project()
        self.project.fit_object(0.35)
        self.project_path = ''
        self.time = 0.0
        self.load_project_into_ui()

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Open project', '', 'Motion Studio project (*.msproj)')
        if not path:
            return
        try:
            with open(path, encoding='utf-8') as f:
                self.project = Project.from_dict(json.load(f))
        except Exception as exc:
            QMessageBox.warning(self, APP_NAME, f'Could not open the project:\n{exc}')
            return
        self.project_path = path
        self.time = 0.0
        self.load_project_into_ui()

    def save_project(self, save_as=False):
        path = self.project_path
        if save_as or not path:
            path, _ = QFileDialog.getSaveFileName(self, 'Save project', 'animation.msproj',
                                                  'Motion Studio project (*.msproj)')
            if not path:
                return
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(self.project.to_dict(), f, indent=2)
        os.replace(tmp, path)
        self.project_path = path
        self.statusBar().showMessage(f'Saved {path}', 4000)

    # ---- export

    def export_dialog(self):
        self.stop()
        dlg = QDialog(self)
        dlg.setWindowTitle('Export')
        lay = QVBoxLayout(dlg)
        radios = {}
        for key, label in FORMATS.items():
            r = QRadioButton(label)
            radios[key] = r
            lay.addWidget(r)
        radios['prores'].setChecked(True)
        pr = self.project
        lay.addWidget(QLabel(f'{pr.width}×{pr.height}, {pr.fps:g} frames/s, {pr.duration:g} s '
                             f'({pr.frame_count()} frames). Transparent background.'))
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        fmt = 'prores' if radios['prores'].isChecked() else 'png'
        if fmt == 'prores':
            path, _ = QFileDialog.getSaveFileName(self, 'Export video', 'animation.mov', 'ProRes video (*.mov)')
        else:
            path = QFileDialog.getExistingDirectory(self, 'Folder for the PNG frames')
        if not path:
            return
        self._run_export(path, fmt)

    def _run_export(self, path, fmt):
        prog = QProgressDialog('Exporting…', 'Cancel', 0, self.project.frame_count(), self)
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(0)
        self._thread = QThread(self)
        self._worker = ExportWorker(self.project.to_dict(), path, fmt)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(lambda d, t: prog.setValue(d))
        prog.canceled.connect(lambda: setattr(self._worker, 'cancel', True))

        def done(p, err):
            prog.close()
            self._thread.quit()
            self._thread.wait()
            if err == 'cancelled':
                self.statusBar().showMessage('Export cancelled.', 4000)
            elif err:
                QMessageBox.warning(self, APP_NAME, f'Export failed:\n{err}')
            else:
                self.statusBar().showMessage(f'Exported {p}', 8000)
                QMessageBox.information(self, APP_NAME, f'Exported:\n{p}')

        self._worker.finished.connect(done)
        self._thread.start()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName('StrokeDot')
    app.setStyle('Fusion')
    from PySide6.QtGui import QPalette
    pal = QPalette()
    for role, col in ((QPalette.ColorRole.Window, '#23262d'), (QPalette.ColorRole.WindowText, '#e6e8ec'),
                      (QPalette.ColorRole.Base, '#1b1d22'), (QPalette.ColorRole.AlternateBase, '#2a2d34'),
                      (QPalette.ColorRole.Text, '#e6e8ec'), (QPalette.ColorRole.Button, '#2f333b'),
                      (QPalette.ColorRole.ButtonText, '#e6e8ec'), (QPalette.ColorRole.Highlight, '#3a9d7d'),
                      (QPalette.ColorRole.HighlightedText, '#ffffff'), (QPalette.ColorRole.ToolTipBase, '#2f333b'),
                      (QPalette.ColorRole.ToolTipText, '#e6e8ec')):
        pal.setColor(role, QColor(col))
    app.setPalette(pal)
    w = MainWindow()
    w.show()
    if len(sys.argv) > 1 and sys.argv[1].endswith('.msproj'):
        w.project_path = sys.argv[1]
        with open(sys.argv[1], encoding='utf-8') as f:
            w.project = Project.from_dict(json.load(f))
        w.load_project_into_ui()
    sys.exit(app.exec())

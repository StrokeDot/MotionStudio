"""Right-hand Properties panel for the selected sticker: Sticker, Transitions and
Effects pages, with Filmora-style slider rows."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox,
                               QFontComboBox, QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel,
                               QPlainTextEdit, QPushButton, QScrollArea, QSlider, QSpinBox, QToolButton,
                               QVBoxLayout, QWidget)

from .document import Document, transition_names
from .effects import EASINGS, IN_OUT_BY_NAME
from .library import read_presets, write_presets
from .theme import ACCENT, LINE, MUTED, PANEL_2, TEXT, icon

ARROWS = {'up-left': '↖', 'up': '↑', 'up-right': '↗', 'left': '←', 'right': '→',
          'down-left': '↙', 'down': '↓', 'down-right': '↘'}
GRID = [['up-left', 'up', 'up-right'], ['left', None, 'right'], ['down-left', 'down', 'down-right']]


class SliderRow(QWidget):
    """Label · slider · value · reset, like Filmora's property rows."""

    edited = Signal(float)
    started = Signal()

    def __init__(self, label, lo, hi, value, default, decimals=0, suffix=''):
        super().__init__()
        self.lo, self.hi, self.default, self.decimals = lo, hi, default, decimals
        self.steps = 1000
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lab = QLabel(label)
        lab.setMinimumWidth(96)
        lay.addWidget(lab)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, self.steps)
        lay.addWidget(self.slider, 1)
        self.spin = QDoubleSpinBox()
        self.spin.setRange(lo, hi)
        self.spin.setDecimals(decimals)
        self.spin.setSuffix(suffix)
        self.spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self.spin.setProperty('compact', True)
        self.spin.setFixedWidth(70)
        self.spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        lay.addWidget(self.spin)
        self.reset_btn = QToolButton()
        self.reset_btn.setIcon(icon('reset', MUTED))
        self.reset_btn.setToolTip('Reset')
        lay.addWidget(self.reset_btn)
        self.set_value(value)
        self.slider.sliderPressed.connect(self.started)
        self.slider.valueChanged.connect(self._from_slider)
        self.spin.editingFinished.connect(self._from_spin)
        self.reset_btn.clicked.connect(self._reset)

    def set_value(self, v):
        self.slider.blockSignals(True)
        self.spin.blockSignals(True)
        self.spin.setValue(v)
        self.slider.setValue(int(round((v - self.lo) / max(1e-9, self.hi - self.lo) * self.steps)))
        self.slider.blockSignals(False)
        self.spin.blockSignals(False)

    def _from_slider(self, s):
        if not self.slider.isSliderDown():
            self.started.emit()
        v = self.lo + (self.hi - self.lo) * s / self.steps
        v = round(v, self.decimals)
        self.spin.blockSignals(True)
        self.spin.setValue(v)
        self.spin.blockSignals(False)
        self.edited.emit(v)

    def _from_spin(self):
        self.started.emit()
        self.set_value(self.spin.value())
        self.edited.emit(self.spin.value())

    def _reset(self):
        self.started.emit()
        self.set_value(self.default)
        self.edited.emit(self.default)


class DirectionPicker(QWidget):
    picked = Signal(str)

    def __init__(self, value: str, only=None):
        super().__init__()
        grid = QGridLayout(self)
        grid.setSpacing(3)
        grid.setContentsMargins(0, 0, 0, 0)
        group = QButtonGroup(self)
        for r, row in enumerate(GRID):
            for c, name in enumerate(row):
                if name is None:
                    continue
                b = QToolButton()
                b.setText(ARROWS[name])
                b.setCheckable(True)
                b.setFixedSize(34, 28)
                b.setStyleSheet(f'QToolButton{{background:{PANEL_2};border:1px solid {LINE};font-size:15px;}}'
                                f'QToolButton:checked{{border-color:{ACCENT};color:{ACCENT};}}')
                b.setToolTip(name.replace('-', ' '))
                b.setChecked(name == value)
                b.setEnabled(only is None or name in only)
                group.addButton(b)
                b.clicked.connect(lambda _=False, n=name: self.picked.emit(n))
                grid.addWidget(b, r, c)


def _section(title: str) -> QLabel:
    lab = QLabel(title)
    lab.setStyleSheet(f'color:{TEXT}; font-weight:600; font-size:13px; padding-top:8px;')
    return lab


def _line() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet(f'color:{LINE}; background:{LINE}; max-height:1px;')
    return f


def _labeled(label: str, w: QWidget) -> QWidget:
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 2, 0, 2)
    lab = QLabel(label)
    lab.setMinimumWidth(96)
    lay.addWidget(lab)
    lay.addWidget(w, 1)
    return row


class PropertiesPanel(QWidget):
    message = Signal(str)
    library_changed = Signal()

    PAGES = ['Sticker', 'Transitions', 'Effects']

    def __init__(self, doc: Document):
        super().__init__()
        self.doc = doc
        self.page = 'Sticker'
        self._own = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 8)
        head = QLabel('Properties')
        head.setProperty('heading', True)
        lay.addWidget(head)
        tabs = QHBoxLayout()
        self.page_buttons = {}
        for name in self.PAGES:
            b = QPushButton(name)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, n=name: self.show_page(n))
            self.page_buttons[name] = b
            tabs.addWidget(b)
        tabs.addStretch(1)
        lay.addLayout(tabs)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lay.addWidget(self.scroll, 1)
        doc.selection_changed.connect(self.rebuild)
        doc.changed.connect(self._doc_changed)
        self.rebuild()

    # ---- plumbing

    def _doc_changed(self):
        if not self._own:
            QTimer.singleShot(0, self.rebuild)

    def _edit(self, fn, *args):
        """Apply an edit from this panel without rebuilding the panel."""
        self._own = True
        try:
            fn(*args)
            self.doc.notify()
        finally:
            self._own = False

    def show_page(self, name):
        self.page = name
        self.rebuild()

    def rebuild(self):
        clip = self.doc.selected()
        for n, b in self.page_buttons.items():
            b.setChecked(n == self.page)
            b.setVisible(clip is not None)
            b.setStyleSheet(f'color:{ACCENT}; border-color:{ACCENT};' if n == self.page else '')
        pos = self.scroll.verticalScrollBar().value()
        w = QWidget()
        self.body = QVBoxLayout(w)
        self.body.setContentsMargins(0, 4, 4, 4)
        self.body.setSpacing(2)
        if clip is None:
            self._build_empty()
        elif self.page == 'Sticker':
            self._build_sticker(clip)
        elif self.page == 'Transitions':
            self._build_transitions(clip)
        else:
            self._build_effects(clip)
        self.body.addStretch(1)
        self.scroll.setWidget(w)
        QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(pos))

    def _slider(self, label, lo, hi, get, set_, default, decimals=0, suffix=''):
        row = SliderRow(label, lo, hi, get(), default, decimals, suffix)
        row.started.connect(self.doc.checkpoint)
        row.edited.connect(lambda v: self._edit(set_, v))
        self.body.addWidget(row)
        return row

    # ---- pages

    def _build_empty(self):
        tl = self.doc.timeline
        lab = QLabel('Nothing selected.\n\nAdd a sticker from the Stickers tab, then select it on the '
                     'timeline or in the player to edit it here.')
        lab.setWordWrap(True)
        lab.setProperty('muted', True)
        self.body.addWidget(lab)
        self.body.addWidget(_section('Video'))
        fps = QComboBox()
        fps.addItems(['24', '25', '30', '50', '60'])
        fps.setCurrentText(f'{tl.fps:g}')

        def set_fps(text):
            self.doc.checkpoint()
            self._edit(setattr, tl, 'fps', float(text))
        fps.currentTextChanged.connect(set_fps)
        self.body.addWidget(_labeled('Frames / s', fps))
        info = QLabel(f'{tl.width} × {tl.height}   ·   change the size under the player')
        info.setProperty('muted', True)
        self.body.addWidget(info)

    def _build_sticker(self, clip):
        tl = self.doc.timeline
        src = clip.source
        if src.kind == 'text':
            st = src.text
            self.body.addWidget(_section('Text'))
            te = QPlainTextEdit(st.text)
            te.setFixedHeight(64)
            started = {'v': False}

            def text_changed():
                if not started['v']:
                    self.doc.checkpoint()
                    started['v'] = True
                self._edit(setattr, st, 'text', te.toPlainText())
            te.textChanged.connect(text_changed)
            self.body.addWidget(te)
            font = QFontComboBox()
            font.setCurrentFont(QFont(st.family))
            font.currentFontChanged.connect(lambda f: (self.doc.checkpoint(), self._edit(setattr, st, 'family', f.family())))
            self.body.addWidget(_labeled('Font', font))
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            for attr, label in (('bold', 'Bold'), ('italic', 'Italic')):
                cb = QCheckBox(label)
                cb.setChecked(getattr(st, attr))
                cb.toggled.connect(lambda v, a=attr: (self.doc.checkpoint(), self._edit(setattr, st, a, v)))
                rl.addWidget(cb)
            rl.addStretch(1)
            self.body.addWidget(row)
            self._slider('Font size', 8, 600, lambda: st.size, lambda v: setattr(st, 'size', v), 120)
            for attr, label in (('color', 'Colour'), ('outline_color', 'Outline colour')):
                self.body.addWidget(_labeled(label, self._color_button(lambda a=attr: getattr(st, a),
                                                                       lambda c, a=attr: setattr(st, a, c))))
            self._slider('Outline', 0, 60, lambda: st.outline_width, lambda v: setattr(st, 'outline_width', v), 6, 1)
        else:
            lab = QLabel(f'{clip.name()}   ·   {src.kind}')
            lab.setProperty('muted', True)
            self.body.addWidget(lab)

        self.body.addWidget(_section('Placement'))
        self._slider('Position X', -50, 150, lambda: clip.x * 100, lambda v: setattr(clip, 'x', v / 100), 50, 1, ' %')
        self._slider('Position Y', -50, 150, lambda: clip.y * 100, lambda v: setattr(clip, 'y', v / 100), 50, 1, ' %')
        self._slider('Size', 1, 800, lambda: clip.scale * 100, lambda v: setattr(clip, 'scale', v / 100),
                     100, 1, ' %')
        self._slider('Rotation', -180, 180, lambda: clip.rotation, lambda v: setattr(clip, 'rotation', v), 0, 1, '°')
        self._slider('Opacity', 0, 100, lambda: clip.opacity * 100, lambda v: setattr(clip, 'opacity', v / 100),
                     100, 0, ' %')
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 4, 0, 0)
        centre = QPushButton('Centre')
        fit = QPushButton('Fit to video')
        centre.clicked.connect(lambda: (self.doc.checkpoint(),
                                        self._edit(lambda: (setattr(clip, 'x', 0.5), setattr(clip, 'y', 0.5))),
                                        self.rebuild()))
        fit.clicked.connect(lambda: (self.doc.checkpoint(), self._edit(clip.fit, tl.width, tl.height, 0.5),
                                     self.rebuild()))
        rl.addWidget(centre)
        rl.addWidget(fit)
        self.body.addWidget(row)

        self.body.addWidget(_section('Timing'))
        self._slider('Starts at', 0, max(60, clip.end + 10), lambda: clip.start,
                     lambda v: setattr(clip, 'start', v), 0, 2, ' s')
        self._slider('Length', 0.1, max(30, clip.duration * 2), lambda: clip.duration,
                     lambda v: setattr(clip, 'duration', v), 4, 2, ' s')

    def _color_button(self, get, set_):
        b = QPushButton(get())

        def paint():
            c = get()
            b.setText(c)
            b.setStyleSheet(f'background:{c}; color:{"#000" if QColor(c).lightness() > 128 else "#fff"};')

        def pick():
            c = QColorDialog.getColor(QColor(get()), self, 'Choose colour')
            if c.isValid():
                self.doc.checkpoint()
                self._edit(set_, c.name())
                paint()
        paint()
        b.clicked.connect(pick)
        return b

    def _build_transitions(self, clip):
        names = ['None'] + transition_names()
        for which, title in (('in', 'In  (start of the sticker)'), ('out', 'Out  (end of the sticker)')):
            ph = clip.trans_in if which == 'in' else clip.trans_out
            self.body.addWidget(_section(title))
            combo = QComboBox()
            combo.addItems(names)
            combo.setCurrentText(ph.effect)

            def changed(name, w=which):
                cur = clip.trans_in if w == 'in' else clip.trans_out
                if name == cur.effect:
                    return
                self.doc.checkpoint()
                self._edit(setattr, cur, 'effect', name)
                if cur.duration > clip.duration:
                    cur.duration = max(0.2, clip.duration / 3)
                self.rebuild()
            combo.currentTextChanged.connect(changed)
            self.body.addWidget(_labeled('Transition', combo))
            info = IN_OUT_BY_NAME.get(ph.effect)
            if ph.effect == 'None' or info is None:
                continue
            hint = QLabel(info.hint)
            hint.setWordWrap(True)
            hint.setProperty('muted', True)
            self.body.addWidget(hint)
            if info.direction:
                only = ('left', 'right') if ph.effect == 'Spin' else None
                if only and ph.direction not in only:
                    ph.direction = 'right'
                dp = DirectionPicker(ph.direction, only)
                dp.picked.connect(lambda d, p=ph: (self.doc.checkpoint(), self._edit(setattr, p, 'direction', d)))
                self.body.addWidget(_labeled('Turns' if only else 'Moves', dp))
            self._slider('Duration', 0.05, max(0.1, min(20, clip.duration)), lambda p=ph: p.duration,
                         lambda v, p=ph: setattr(p, 'duration', v), 1.0, 2, ' s')
            if info.easing:
                ec = QComboBox()
                ec.addItems(list(EASINGS))
                ec.setCurrentText(ph.easing)
                ec.currentTextChanged.connect(lambda t, p=ph: (self.doc.checkpoint(), self._edit(setattr, p, 'easing', t)))
                self.body.addWidget(_labeled('Easing', ec))
            if info.distance:
                self._slider('Distance', 1, 400, lambda p=ph: p.distance, lambda v, p=ph: setattr(p, 'distance', v),
                             100, 0, ' %')
            if info.amount:
                self._slider('Strength', 1, 500, lambda p=ph: p.amount, lambda v, p=ph: setattr(p, 'amount', v),
                             100, 0, ' %')
            if info.bounces:
                self._slider('Bounces', 1, 6, lambda p=ph: p.bounces, lambda v, p=ph: setattr(p, 'bounces', int(v)), 3)
            if info.fade:
                cb = QCheckBox('Fade while moving')
                cb.setChecked(ph.fade)
                cb.toggled.connect(lambda v, p=ph: (self.doc.checkpoint(), self._edit(setattr, p, 'fade', v)))
                self.body.addWidget(cb)
            save = QPushButton('Save to Mine…')
            save.clicked.connect(lambda _=False, p=ph: self._save_transition(p))
            self.body.addWidget(save)
            self.body.addWidget(_line())

    def _save_transition(self, ph):
        name, ok = QInputDialog.getText(self, 'Save transition', 'Name:', text=f'{ph.effect} {ph.direction}')
        if ok and name.strip():
            data = read_presets()
            data.setdefault('transition', {})[name.strip()] = ph.to_dict()
            write_presets(data)
            self.library_changed.emit()
            self.message.emit(f'Saved "{name.strip()}" to Transitions › Mine')

    def _build_effects(self, clip):
        if not clip.effects:
            lab = QLabel('No effects yet.\n\nOpen the Effects tab in the library and drag one onto this '
                         'sticker, or click its + button.')
            lab.setWordWrap(True)
            lab.setProperty('muted', True)
            self.body.addWidget(lab)
            return
        for e in list(clip.effects):
            info = e.info()
            head = QWidget()
            hl = QHBoxLayout(head)
            hl.setContentsMargins(0, 8, 0, 2)
            on = QCheckBox()
            on.setChecked(e.enabled)
            on.setToolTip('On / off')
            on.toggled.connect(lambda v, ef=e: (self.doc.checkpoint(), self._edit(setattr, ef, 'enabled', v)))
            hl.addWidget(on)
            name = QLabel(info.name)
            name.setStyleSheet('font-weight:600;')
            hl.addWidget(name, 1)
            for ic, tip, fn in (('reset', 'Reset to defaults', lambda _=False, ef=e: self._reset_effect(ef)),
                                ('save', 'Save to Mine', lambda _=False, ef=e: self._save_effect(ef)),
                                ('delete', 'Remove effect', lambda _=False, ef=e: self._remove_effect(clip, ef))):
                b = QToolButton()
                b.setIcon(icon(ic, MUTED))
                b.setToolTip(tip)
                b.clicked.connect(fn)
                hl.addWidget(b)
            self.body.addWidget(head)
            for prm in info.params:
                if prm.kind in ('float', 'int'):
                    self._slider(prm.label, prm.min, prm.max, lambda ef=e, k=prm.id: float(ef.params[k]),
                                 lambda v, ef=e, k=prm.id, kind=prm.kind: ef.params.__setitem__(
                                     k, int(round(v)) if kind == 'int' else v),
                                 prm.default, 0 if prm.kind == 'int' else 2)
                elif prm.kind == 'color':
                    self.body.addWidget(_labeled(prm.label, self._color_button(
                        lambda ef=e, k=prm.id: ef.params[k],
                        lambda c, ef=e, k=prm.id: ef.params.__setitem__(k, c))))
                elif prm.kind == 'direction':
                    only = ('left', 'right') if e.type == 'spin' else None
                    dp = DirectionPicker(e.params[prm.id], only)
                    dp.picked.connect(lambda d, ef=e, k=prm.id: (self.doc.checkpoint(),
                                                                 self._edit(ef.params.__setitem__, k, d)))
                    self.body.addWidget(_labeled(prm.label, dp))
            self.body.addWidget(_line())

    def _reset_effect(self, e):
        self.doc.checkpoint()
        self._edit(e.reset)
        self.rebuild()

    def _remove_effect(self, clip, e):
        self.doc.checkpoint()
        self._edit(clip.effects.remove, e)
        self.rebuild()

    def _save_effect(self, e):
        name, ok = QInputDialog.getText(self, 'Save effect', 'Name:', text=f'My {e.info().name}')
        if ok and name.strip():
            data = read_presets()
            data.setdefault('effect', {})[name.strip()] = {'type': e.type, 'params': dict(e.params)}
            write_presets(data)
            self.library_changed.emit()
            self.message.emit(f'Saved "{name.strip()}" to Effects › Mine')
